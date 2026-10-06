import asyncio
import logging

from memory.repository import JobAlreadyRunning
from wechat.crypto import mask_openid

logger = logging.getLogger(__name__)
SLOW_REPLY = "这个问题需要更多时间处理。请稍后发送“结果”。"
BUSY_REPLY = "当前已有一个任务正在处理中。请稍后发送“结果”查看。"


class MessageRouter:
    def __init__(self, state, repository, runtime):
        self.state, self.repository, self.runtime = state, repository, runtime
        self.active_tasks: dict[str, asyncio.Task] = {}

    def get_job_result(self, openid: str) -> str:
        job = self.repository.latest_job(openid)
        if job is None:
            return "当前没有正在处理或等待查看的任务。"
        if job['status'] == 'processing':
            return "任务仍在处理中，请稍后再试。"
        if job['status'] == 'done':
            return job['answer'] or "任务已经完成，但没有获得有效结果。"
        if job['error'] == 'interrupted_by_restart':
            return "上一次任务因程序重启而中断，请重新发送问题。"
        return "任务处理失败，请重新发送问题。"

    def _reply(self, openid, text):
        self.repository.add_message(openid, 'assistant', text)
        return text

    async def _run_job(self, job):
        openid, job_id, mode = job['openid'], job['id'], job['mode']
        logger.info("Job started id=%s openid=%s mode=%s", job_id, mask_openid(openid), mode)
        try:
            runner = self.runtime.run_agent if mode == 'ai-agent' else self.runtime.run_simple_answer
            answer = await runner(openid, job['question'])
            self.repository.finish_job(job_id, answer=answer)
            logger.info("Job status=done id=%s mode=%s", job_id, mode)
            return answer
        except asyncio.CancelledError:
            self.repository.finish_job(job_id, error='interrupted_by_restart')
            raise
        except Exception as exc:
            # Never persist external exception text or a vendor response body.
            self.repository.finish_job(job_id, error='ai_request_failed')
            logger.error("Job status=error id=%s mode=%s error_type=%s", job_id, mode, type(exc).__name__)
            return "AI 服务暂时出现异常，请稍后重新发送问题。"

    async def handle_text(self, openid: str, text: str) -> str:
        text = text.strip()
        user = self.repository.ensure_user(openid)
        self.repository.add_message(openid, 'user', text)
        snapshot = self.state.snapshot()
        features = snapshot.features
        if text == features.agent_enable_phrase:
            if not features.ai_agent_enabled:
                return self._reply(openid, "Agent功能当前已关闭。")
            if not features.allow_user_agent_self_enable:
                return self._reply(openid, "请联系管理员开启Agent功能。")
            self.repository.set_agent_enabled(openid, True)
            return self._reply(openid, "豆包Agent功能已开启。")
        if text == features.agent_disable_phrase:
            self.repository.set_agent_enabled(openid, False)
            return self._reply(openid, "豆包Agent功能已关闭。")
        if text == '结果':
            return self._reply(openid, self.get_job_result(openid))
        if user['agent_enabled']:
            if not features.ai_agent_enabled:
                return self._reply(openid, "Agent功能当前已关闭。")
            mode = 'ai-agent'
        else:
            if not features.ai_answer_enabled:
                return self._reply(openid, "AI回答功能当前已关闭。")
            mode = 'ai-answer'
        try:
            job = self.repository.create_job(openid, mode, text)
        except JobAlreadyRunning:
            return self._reply(openid, BUSY_REPLY)
        task = asyncio.create_task(self._run_job(job))
        self.active_tasks[job['id']] = task
        task.add_done_callback(lambda completed: self.active_tasks.pop(job['id'], None))
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=snapshot.fast_reply_timeout_seconds)
        except asyncio.TimeoutError:
            return self._reply(openid, SLOW_REPLY)

    async def shutdown(self):
        tasks = list(self.active_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
