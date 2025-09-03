from concurrent.futures import ThreadPoolExecutor

from .logger import Logger


class Threaded:
    def __init__(self, max_workers=10):
        self.thread_pool = ThreadPoolExecutor(max_workers)
        self.threads = []
        self.results = []
        self.log = Logger(__name__)

    def run(self, fn, *args, **kwargs):
        self.log.debug(f"Running {fn.__name__} with args: {args} and kwargs: {kwargs}")
        thread = self.thread_pool.submit(fn, *args, **kwargs)
        self.threads.append(thread)
        return thread

    def wait(self):
        if not self.threads:
            self.log.debug("No threads to wait for")
            return self.results
            
        self.log.debug(f"Waiting for {len(self.threads)} threads to finish...")
        for t in self.threads:
            self.results.append(t.result())
        
        # Clear threads list after waiting
        self.threads.clear()
        return self.results

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.thread_pool.shutdown(wait=True)

