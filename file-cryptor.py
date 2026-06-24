import argparse
from cryptography.fernet import Fernet, InvalidToken
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser()
group=parser.add_mutually_exclusive_group()

parser.add_argument("action", help="Operation to perform (encrypt, decrypt, genkey)", choices=["encrypt", "decrypt", "genkey"], type=str)
parser.add_argument("-p","--path", help="Target file or directory to process (defaults to current directory if not set)", type=str, default=None, required=False)
parser.add_argument("-k", "--key", help="Path to the Fernet key file (required for encrypt/decrypt)", required=False)
group.add_argument("-o", "--output", help="Output file or directory for results (used instead of modifying files in place)", type=str, default=None)
group.add_argument("-i","--inplace", help="Modify files directly (overwrites original files safely using a temporary file)", action="store_true")
parser.add_argument("-r", "--recursive", help="Process directories recursively (required when -p is a folder)", action="store_true")
parser.add_argument("-q", "--quiet", help="Enables quiet mode", action="store_true")

args=parser.parse_args()



def process_file(file_path, output_path, fernet, action, quiet, inplace=False):
    """
    Handles the reading, encrypting/decrypting, and writing of a single file.
    Returns True on success, False on failure.
    """

    temp_path=None

    try:                                                                    #Safely read file
        with open(file_path, "rb") as f:
            content=f.read()
    except (FileNotFoundError, PermissionError) as e:
        if not quiet:
            print(f"[-] Cannot read {file_path}: {type(e).__name__}")
        return False
    except MemoryError:                                                     #Handle files larger than available RAM
        if not quiet:
            print(f"[-] File too large to process in memory: {file_path}")
        return False



    if action=="encrypt":
        processed=fernet.encrypt(content)                                   #Encrypts
    else:
        try:
            processed=fernet.decrypt(content)
        except InvalidToken:
            if not quiet:
                print(f"[-] Invalid token or wrong key: {file_path}")
            return False


    if inplace:                                                                     # Inplace safety mechanism: Write to a temporary file first to prevent data corruption if the process crashes or disk fills up during writing
        temp_path = output_path.with_name(output_path.name + ".tmp")        
        write_path = temp_path
    else:
        write_path = output_path


    try:                                                                    #Safely writes processed data
        with open(write_path, "wb") as f:
            f.write(processed)


        if inplace:                                                                 # Writing succeeded + we are in inplace mode --> replace the original
            temp_path.replace(output_path)
        

        if not quiet:
            print(f"[+] File {action}ed successfully: {output_path}")
    
        return True

    except PermissionError:
        if not quiet:
            print(f"[-] No permission to write: {output_path}")
        
        if inplace and temp_path is not None and temp_path.exists():                        #Delete temporary file if it was created and the write failed
            temp_path.unlink()                                                              #Deletes file from file system
        return False




if __name__=="__main__":
    time_start=time.time()
    if args.action=="genkey":
        key=Fernet.generate_key()

        if args.output:
            out_path=Path(args.output)

            if out_path.is_dir() or str(args.output).endswith(("/", "\\")):                         #Provided path is a directory path (ends with slash or actually is a dir)
                key_path=out_path/"fernet_key.key"
            else:
                key_path=out_path
        else:
            key_path=Path("fernet_key.key")



        if key_path.exists():
            stem=key_path.stem
            suffix=key_path.suffix
            parent=key_path.parent

                                                                                                    #Avoids overwriting existing keys:
            i=1
            while key_path.exists():
                key_path=parent/f"{stem}_{i}{suffix}"
                i+=1

        key_path.parent.mkdir(parents=True, exist_ok=True)                                                  #Create parent directories if they don't exist (e.g., -o keys/my_key.key)




        with open(key_path, "wb") as f:
            f.write(key)

        elapsed_time=time.time()-time_start

        try:
            key_path.chmod(0o600)                               #Windows may raise errors depending on its configuration --> except
        except Exception:
            pass

        if not args.quiet:
            print(f"[+] Key generated successfully in {elapsed_time:.3f} seconds: {key_path}")


    else:
        if not args.key:
            if not args.quiet:
                print("[-] Missing key file path")
            sys.exit(1)

        key_path=Path(args.key)
        if not key_path.exists() or key_path.is_dir():
            if not args.quiet:
                print("[-] Invalid key file path")
            sys.exit(1)

        if not args.path:
            if not args.quiet:
                print("[-] Missing path")
            sys.exit(1)
        
        path=Path(args.path)

        if path.is_dir() and not args.recursive:                                        #Prevents processing directory without -r flag
            if not args.quiet:
                print("[-] No file provided")
            sys.exit(1)


        with open(key_path, "rb") as f:
            key=f.read()

        try:
            fernet=Fernet(key)
        except (ValueError, TypeError):
            if not args.quiet:
                print("[-] Invalid or corrupted key file")
            sys.exit(1)


        if path.is_dir():
            files_to_process = [f for f in path.rglob("*") if f.is_file()]                  #path.rglob("*") --> Recursively collects all files from the target directory and its subdirectories
        else:
            files_to_process = [path]


        success_count=0
        error_count=0


        if args.output:
            base_output = Path(args.output)
            is_dir_target = str(args.output).endswith(("/", "\\")) or (base_output.exists() and base_output.is_dir())                   #HEURISTIC: It's a directory if it ends with a slash OR if it exists and is a directory
        else:
            base_output = None
            is_dir_target = False

        for file_path in files_to_process:                                                                                          #Process each file
            #Determine final outpu path for this file
            if args.output:
                if is_dir_target:
                    try:
                        rel_path = file_path.relative_to(path)                                                                      #Convert absolute path to a relative one (e.g. /root/a/b.txt -> a/b.txt)
                    except ValueError:                                                                                              #relative_to() fails if the file is not actually under the expected base path (e.g. different root or symlink/mismatch), even if rglob found it
                        if not args.quiet:
                            print(f"[!] Warning: Cannot preserve structure for {file_path}. Flattening output.")
                        rel_path=file_path.name
                    output_path = base_output / rel_path
                
                else:
                    output_path=base_output

            elif args.inplace:
                output_path=file_path
            else:
                if args.action=="encrypt":
                    output_path=file_path.with_name(file_path.name + ".enc")                            #encrypted file --> add extension .enc
                else:
                    output_path=file_path.with_suffix("")                                               #decrypted file --> remove extension .enc


            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)                                   #creates the output directory structure if it doesn't exist yet
            except (PermissionError, OSError):
                if not args.quiet:
                    print(f"[-] Cannot create directory: {output_path.parent}")
                error_count+=1
                continue

            if process_file(file_path, output_path, fernet, args.action, args.quiet, inplace=args.inplace):
                success_count+=1
            else:
                error_count+=1


        elapsed_time = time.time() - time_start
        if not args.quiet:
            print(f"\n[INFO] Process completed in {elapsed_time:.3f} seconds")
            print(f"[INFO] Successfully processed: {success_count} | Failed: {error_count}")

        if error_count > 0:
            sys.exit(1)
        sys.exit(0)