import pytest

from memory.db import Database
from memory.repository import JobAlreadyRunning, Repository
from memory.search import search_memory


@pytest.mark.parametrize('fts', [True, False])
def test_search_isolation_and_safe_query(tmp_path, fts):
    database = Database(str(tmp_path / 'memory.db'), enable_fts=fts)
    repo = Repository(database)
    repo.save_memory('user-a', 'project', 'My project uses FastAPI and 微信加密消息')
    repo.save_memory('user-b', 'decision', 'FastAPI secret belonging to another user')
    matches = search_memory(repo, 'user-a', 'FastAPI')
    assert len(matches) == 1 and 'another user' not in str(matches)
    assert search_memory(repo, 'user-a', '微信加密')
    assert not search_memory(repo, 'user-a', "' OR 1=1 --")
    assert not search_memory(repo, 'user-a', '%')
    assert not search_memory(repo, 'user-a', '" OR *')
    database.close()


def test_restart_preserves_flags_and_answers(tmp_path):
    path = str(tmp_path / 'memory.db')
    database = Database(path)
    repo = Repository(database)
    assert repo.ensure_user('a')['agent_enabled'] == 0
    repo.set_agent_enabled('a', True)
    job = repo.create_job('a', 'ai-answer', 'question')
    with pytest.raises(JobAlreadyRunning):
        repo.create_job('a', 'ai-answer', 'another question')
    repo.finish_job(job['id'], answer='durable answer')
    repo.ensure_user('b')
    interrupted = repo.create_job('b', 'ai-agent', 'interrupted question')
    database.close()
    database = Database(path)
    repo = Repository(database)
    repo.recover_interrupted_jobs()
    assert repo.latest_job('a')['answer'] == 'durable answer'
    assert repo.get_user('a')['agent_enabled'] == 1
    assert repo.get_job(interrupted['id'])['error'] == 'interrupted_by_restart'
    assert repo.active_job_count() == 0
    database.close()


def test_conservative_memory_and_summary_updates(services):
    repo = services.repository
    for content in ('你好', '谢谢', 'hello', ''):
        with pytest.raises(ValueError):
            repo.save_memory('a', 'profile', content)
    repo.save_memory('a', 'summary', 'User develops a WeChat agent')
    repo.save_memory('a', 'summary', 'User develops a WeChat agent with SQLite')
    assert len(repo.summaries('a')) == 1
    assert 'SQLite' in repo.summaries('a')[0]['content']
    for content in ('one', 'two', 'three'):
        repo.add_message('a', 'user', content)
    assert [row['content'] for row in repo.recent_messages('a', 2)] == ['two', 'three']
