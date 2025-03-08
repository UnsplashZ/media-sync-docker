# app/sync.py

import os
import sys
import time
import yaml
import logging
import sqlite3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 加载配置
CONFIG_PATH = os.getenv("CONFIG_PATH", "/app/config.yaml")
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("/app/logs/sync.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# 确保缓存目录存在
CACHE_DIR = os.path.dirname(os.getenv("DB_PATH", "/app/cache/sync_cache.db"))
os.makedirs(CACHE_DIR, exist_ok=True)

# 连接缓存数据库
DB_PATH = os.getenv("DB_PATH", "/app/cache/sync_cache.db")
try:
    conn = sqlite3.connect(DB_PATH)
except sqlite3.OperationalError as e:
    logging.error(f"无法打开数据库文件: {DB_PATH}，错误: {e}")
    sys.exit(1)

cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS synced_files (
        source_path TEXT PRIMARY KEY,
        target_path TEXT
    )
''')
conn.commit()

def add_to_cache(source, target):
    cursor.execute('INSERT OR IGNORE INTO synced_files (source_path, target_path) VALUES (?, ?)', (source, target))
    conn.commit()

def remove_from_cache(source):
    cursor.execute('DELETE FROM synced_files WHERE source_path = ?', (source,))
    conn.commit()

def is_in_cache(source):
    cursor.execute('SELECT 1 FROM synced_files WHERE source_path = ?', (source,))
    return cursor.fetchone() is not None

class SyncHandler(FileSystemEventHandler):
    def __init__(self, mapping):
        self.source_dir = os.path.abspath(mapping['source'])
        self.target_dir = os.path.abspath(mapping['target'])
        self.extensions = set(ext.lower() for ext in mapping['extensions'])
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return
        self.handle_event(event.src_path, created=True)

    def on_deleted(self, event):
        if event.is_directory:
            return
        self.handle_event(event.src_path, created=False)

    def handle_event(self, src_path, created=True):
        if not any(src_path.lower().endswith(ext) for ext in self.extensions):
            return

        relative_path = os.path.relpath(src_path, self.source_dir)
        target_path = os.path.join(self.target_dir, relative_path)
        target_dir = os.path.dirname(target_path)

        if created:
            if not is_in_cache(src_path):
                os.makedirs(target_dir, exist_ok=True)
                symlink_path = target_path  # 初始软链接路径
                try:
                    # 创建软链接
                    if not os.path.exists(symlink_path):
                        os.symlink(src_path, symlink_path)
                        os.chmod(symlink_path, 0o777)
                        add_to_cache(src_path, symlink_path)
                        logging.info(f"Created symlink: {symlink_path} -> {src_path}")
                    else:
                        logging.warning(f"Symlink already exists: {symlink_path}")
                except Exception as e:
                    logging.error(f"创建软链接失败: {symlink_path} -> {src_path}，错误: {e}")
        else:
            if is_in_cache(src_path):
                symlink_path = cursor.execute('SELECT target_path FROM synced_files WHERE source_path = ?', (src_path,)).fetchone()[0]
                if os.path.islink(symlink_path):
                    try:
                        os.unlink(symlink_path)
                        logging.info(f"Removed symlink: {symlink_path}")
                    except Exception as e:
                        logging.error(f"删除软链接失败: {symlink_path}，错误: {e}")
                remove_from_cache(src_path)
                # 检查目标目录是否为空
                if not any(os.scandir(target_dir)):
                    try:
                        os.rmdir(target_dir)
                        logging.info(f"Removed empty directory: {target_dir}")
                    except Exception as e:
                        logging.error(f"删除空目录失败: {target_dir}，错误: {e}")

def initial_scan(mapping):
    source_dir = os.path.abspath(mapping['source'])
    target_dir = os.path.abspath(mapping['target'])
    extensions = set(ext.lower() for ext in mapping['extensions'])

    logging.info(f"开始初始扫描: {source_dir} -> {target_dir}")

    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if not any(file.lower().endswith(ext) for ext in extensions):
                continue
            source_path = os.path.join(root, file)
            relative_path = os.path.relpath(source_path, source_dir)
            target_path = os.path.join(target_dir, relative_path)
            if not is_in_cache(source_path):
                target_file_dir = os.path.dirname(target_path)
                os.makedirs(target_file_dir, exist_ok=True)
                try:
                    if not os.path.exists(target_path):
                        os.symlink(source_path, target_path)
                        os.chmod(target_path, 0o777)
                        add_to_cache(source_path, target_path)
                        logging.info(f"初始扫描创建软链接: {target_path} -> {source_path}")
                except Exception as e:
                    logging.error(f"初始扫描创建软链接失败: {target_path} -> {source_path}，错误: {e}")

def main():
    observers = []
    for mapping in config['mappings']:
        event_handler = SyncHandler(mapping)
        observer = Observer()
        observer.schedule(event_handler, path=mapping['source'], recursive=True)
        observer.start()
        observers.append(observer)
        logging.info(f"Started monitoring: {mapping['source']} -> {mapping['target']}")

        # 执行初始扫描
        initial_scan(mapping)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for observer in observers:
            observer.stop()
    for observer in observers:
        observer.join()

if __name__ == "__main__":
    main()