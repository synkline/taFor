import os
import time

def run_automated_cleanup(cache_dir="imd_cache", days=180, limit=1000):
    """
    Scans the cache_dir and its subdirectories (like VABB/), deleting .txt files older than `days`.
    Uses an atomic lock file to ensure Gunicorn workers don't create race conditions or runaway CPU spikes.
    """
    
    if not os.path.exists(cache_dir):
        return

    lockfile = os.path.join(cache_dir, ".cleanup_lock")
    cooldown_seconds = 24 * 60 * 60            
    
    if os.path.exists(lockfile):
        try:
            mtime = os.path.getmtime(lockfile)
            if time.time() - mtime < cooldown_seconds:
                return                 
        except OSError:
                                                                                                  
            return

    fd = None
    try:
        fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                                                                                         
        os.close(fd)
    except FileExistsError:
                                                         
        return
    except OSError as e:
        print(f"[Cleanup] Failed to create lock file: {str(e)}")
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        return

    print(f"\n[Cleanup] Starting automated background cleanup of {cache_dir}...")
    
    max_age_seconds = days * 24 * 60 * 60
    current_time = time.time()
    deleted_count = 0
    
    for root, dirs, files in os.walk(cache_dir):
        for filename in files:
                                                             
            if filename == ".cleanup_lock":
                continue
                
            filepath = os.path.join(root, filename)
            
            try:
                                                          
                file_mtime = os.stat(filepath).st_mtime
                age_seconds = current_time - file_mtime
                
                if age_seconds > max_age_seconds:
                    os.remove(filepath)
                    age_days = round(age_seconds / 86400, 1)
                    print(f"[Cleanup] Deleted: {filepath} (Age: {age_days} days)")
                    
                    deleted_count += 1
                    
                    if deleted_count >= limit:
                        print(f"[Cleanup] Reached safety limit of {limit} deletions. Will continue next cycle.")
                        break
                        
            except OSError as e:
                                                                                                    
                print(f"[Cleanup] Skipping {filepath} due to error: {str(e)}")
                continue
                
        if deleted_count >= limit:
            break

    print(f"[Cleanup] Finished. Deleted {deleted_count} stale files.")

    try:
        os.utime(lockfile, None) 
    except OSError as e:
        print(f"[Cleanup] Failed to update lock timestamp: {str(e)}")
