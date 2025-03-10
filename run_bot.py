import time
import os
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class BotRestarter(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.start_bot()
        
    def start_bot(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
            
        print("Starting bot...")
        self.process = subprocess.Popen([sys.executable, "schedge/bot.py"])
            
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            print(f"Detected change in {event.src_path}")
            self.start_bot()

if __name__ == "__main__":
    path = 'schedge'
    event_handler = BotRestarter()
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if event_handler.process:
            event_handler.process.terminate()
    observer.join() 