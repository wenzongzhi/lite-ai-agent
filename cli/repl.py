import sys
import threading


class Console:
    def __init__(self, dispatcher, input_fn=input, output_fn=print):
        self.dispatcher, self.input_fn, self.output_fn = dispatcher, input_fn, output_fn
        self.stopped = threading.Event()
        self.thread = None

    def start(self, interactive=None):
        if interactive is None:
            interactive = sys.stdin is not None and sys.stdin.isatty()
        if not interactive:
            return False
        self.thread = threading.Thread(target=self.run, name='agent-cli', daemon=True)
        self.thread.start()
        return True

    def run(self):
        self.output_fn("Local agent console. Enter help for commands.")
        while not self.stopped.is_set() and not self.dispatcher.should_quit:
            try:
                line = self.input_fn("agent> ")
            except (EOFError, KeyboardInterrupt):
                break
            if self.stopped.is_set():
                break
            output = self.dispatcher.execute(line)
            if output:
                self.output_fn(output)

    def stop(self):
        # A blocked input() cannot be interrupted portably; this is a daemon thread.
        self.stopped.set()
