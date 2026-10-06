import json
import shlex

from config import ConfigError
from memory.search import search_memory
from wechat.crypto import mask_openid

HELP = """help | status | quit
enable ai-answer | disable ai-answer
enable ai-agent | disable ai-agent
show model | set model <model-id>
show fast-timeout | set fast-timeout <seconds>
config reload
users | jobs
user show <openid>
user agent enable <openid> | user agent disable <openid>
memory stats
memory search <openid> <query>
memory save <openid> <type> <content>
Memory types: preference, project, decision, profile, todo, summary
Runtime changes are not written back to config.toml."""


def parse_command(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        raise ValueError("Invalid command quoting") from None


class CommandDispatcher:
    def __init__(self, services, shutdown=lambda: None):
        self.services, self.shutdown = services, shutdown
        self.should_quit = False

    def execute(self, line: str) -> str:
        try:
            args = parse_command(line)
            if not args:
                return ""
            state, repo = self.services.state, self.services.repository
            snapshot = state.snapshot()
            if args == ['help']:
                return HELP
            if args == ['status']:
                stats = repo.stats()
                available_web = any(tool['function']['name'] == 'web_search' for tool in self.services.registry.schemas())
                return '\n'.join(("server: running", f"ai-answer: {'enabled' if snapshot.features.ai_answer_enabled else 'disabled'}",
                    f"ai-agent: {'enabled' if snapshot.features.ai_agent_enabled else 'disabled'}", f"model: {snapshot.doubao_model}",
                    f"fast-timeout: {snapshot.fast_reply_timeout_seconds:g}s", f"active-jobs: {repo.active_job_count()}",
                    f"users: {stats['users']}", f"db: {self.services.settings.database.path}",
                    f"web-search: {'enabled' if available_web else 'disabled'}", "calendar: disabled (provider not implemented)"))
            if len(args) == 2 and args[0] in ('enable', 'disable'):
                state.set_feature(args[1], args[0] == 'enable')
                return f"{args[1]}: {'enabled' if args[0] == 'enable' else 'disabled'}"
            if args == ['show', 'model']:
                return snapshot.doubao_model
            if args == ['show', 'fast-timeout']:
                return f"{snapshot.fast_reply_timeout_seconds:g}s"
            if len(args) == 3 and args[:2] == ['set', 'model']:
                state.set_model(args[2])
                return "model updated"
            if len(args) == 3 and args[:2] == ['set', 'fast-timeout']:
                try:
                    seconds = float(args[2])
                except ValueError:
                    return "Error: invalid fast-timeout"
                state.set_fast_timeout(seconds)
                return "fast-timeout updated"
            if args == ['config', 'reload']:
                fields = self.services.reload_config()
                return "Configuration reloaded" + ("; restart required: " + ', '.join(fields) if fields else "")
            if args == ['users']:
                return json.dumps([{**user, 'openid': mask_openid(user['openid'])} for user in repo.list_users()], ensure_ascii=False)
            if args == ['jobs']:
                return json.dumps([{**job, 'openid': mask_openid(job['openid'])} for job in repo.list_jobs()], ensure_ascii=False)
            if len(args) == 3 and args[:2] == ['user', 'show']:
                user = repo.get_user(args[2])
                return json.dumps({**user, 'openid': mask_openid(user['openid'])}, ensure_ascii=False) if user else "User not found"
            if len(args) == 4 and args[:2] == ['user', 'agent'] and args[2] in ('enable', 'disable'):
                repo.set_agent_enabled(args[3], args[2] == 'enable')
                return f"User agent: {'enabled' if args[2] == 'enable' else 'disabled'}"
            if args == ['memory', 'stats']:
                return json.dumps(repo.stats())
            if len(args) >= 4 and args[:2] == ['memory', 'search']:
                return json.dumps({'matches': search_memory(repo, args[2], ' '.join(args[3:]))}, ensure_ascii=False)
            if len(args) >= 5 and args[:2] == ['memory', 'save']:
                repo.save_memory(args[2], args[3], ' '.join(args[4:]))
                return "Memory saved"
            if args == ['quit']:
                self.should_quit = True
                self.shutdown()
                return "Stopping server"
            return "Unknown command. Enter help."
        except ConfigError as exc:
            return f"Error: {exc}"
        except ValueError:
            return "Error: invalid command or value"
        except Exception:
            return "Error: command failed"
