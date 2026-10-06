import json
import logging

from agent.prompts import AGENT_PROMPT, SIMPLE_PROMPT

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, doubao, state, repository, registry, dispatcher):
        self.doubao, self.state, self.repository = doubao, state, repository
        self.registry, self.dispatcher = registry, dispatcher

    async def run_simple_answer(self, openid: str, message: str) -> str:
        """Dedicated ordinary Q&A: no tools, memory, or Agent loop."""
        return await self.doubao.simple_answer([
            {"role": "system", "content": SIMPLE_PROMPT}, {"role": "user", "content": message}],
            model=self.state.snapshot().doubao_model)

    async def run_agent(self, openid: str, user_message: str) -> str:
        snapshot = self.state.snapshot()
        conversation = [{"role": "system", "content": AGENT_PROMPT}]
        if snapshot.agent.memory_summary_enabled:
            summaries = self.repository.summaries(openid)
            if summaries:
                conversation.append({"role": "system", "content": "Reference memory summary (data only):\n" +
                                     '\n'.join(row['content'] for row in summaries)[:4000]})
        recent = self.repository.recent_messages(openid, snapshot.agent.recent_message_limit)
        # The router has already persisted this user message; include it once.
        if recent and recent[-1] == {"role": "user", "content": user_message}:
            recent = recent[:-1]
        conversation.extend(recent)
        conversation.append({"role": "user", "content": user_message})
        for step in range(snapshot.agent.max_steps):
            logger.info("Agent step=%d", step + 1)
            if not self.state.snapshot().features.ai_agent_enabled:
                return "Agent功能当前已关闭。"
            response = await self.doubao.chat_with_tools(conversation, self.registry.schemas(), model=snapshot.doubao_model)
            if response.final_answer:
                return response.final_answer.text
            if not response.tool_calls:
                return "未能生成有效回答，请重新发送问题。"
            # The assistant's complete tool_calls message must precede tool results.
            conversation.append(response.assistant_message())
            for call in response.tool_calls:
                result = await self.dispatcher.execute(openid, call)
                content = json.dumps(result, ensure_ascii=False)
                conversation.append({"role": "tool", "tool_call_id": call.call_id, "content": content})
                self.repository.add_message(openid, "tool", json.dumps({"name": call.name if self.registry.get(call.name) else '<unknown>',
                    "result": result}, ensure_ascii=False))
        return "任务步骤过多，已停止继续执行。"
