from b2sdk.v2 import B2Api, InMemoryAccountInfo
import os 
from dotenv import load_dotenv
import logging
from b2sdk.v3.exception import FileNotPresent

load_dotenv()
log = logging.getLogger(__name__)

class Bucket:
    def __init__(self, key_id=None, app_key=None, bucket_name=None):
        self._key_id = key_id or os.getenv('KEY_ID')
        self._app_key = app_key or os.getenv('APPLICATION_KEY')
        self._bucket_name = bucket_name or os.getenv('BUCKET_NAME')
        self._init_authorisation()

    def _init_authorisation(self):
        info = InMemoryAccountInfo()
        self._b2_api = B2Api(info)
        self._b2_api.authorize_account("production", self._key_id, self._app_key)
        self._bucket = self._b2_api.get_bucket_by_name(self._bucket_name)


    # ==========================================================
    # Files transfert
    # ==========================================================
    def download_file_by_name(self, bucket_path: str, local_path: str) -> bool:
        """Download a file from bucket to local by name"""
        try:
            self._bucket.download_file_by_name(bucket_path).save_to(local_path)
            log.info(f"✅ File downloaded from bucket: {bucket_path} to local: {local_path}")
            return True
        except FileNotPresent:
                log.warning(f"[B2] file={bucket_path} status=not_found")
                return False


    def download_file_by_id(self, file_id: str, local_path: str):
        """Download a file from bucket to local by id"""
        try:
            self._b2_api.download_file_by_id(file_id).save_to(local_path)
            log.info(f"✅ File downloaded from bucket id: {file_id} to local: {local_path}")
            return True
        except FileNotPresent:
                log.warning(f"[B2] file_id={file_id} status=not_found")
                return False


    def upload_file(self, bucket_path: str, local_path: str) -> dict:
        """
        Upload a file to a bucket 
        Return a dict with name, id, size about this new file
        """
        file_version = self._bucket.upload_local_file(
            local_file=local_path,
            file_name=bucket_path
        )
        log.info(f"✅ File uploaded from local: {local_path} to bucket: {bucket_path}")
        return {
            "name": file_version.file_name,
            "id": file_version.id_,
            "size": file_version.size
        }

    # ==========================================================
    # Files manipulation
    # ==========================================================
    def delete_file_by_id(self, file_id: str, file_name: str) -> bool:
        try:
            self._bucket.delete_file_version(file_id, file_name)
            log.info(f"✅ File deleted id: {file_id}, name: {file_name}")
        except FileNotPresent:
            log.warning(f"[B2] file_name={file_name}, file_id={file_id} status=not_found")
            return False

    def move_file(self, source_file_name: str, destination_file_name: str, source_file_id: str) -> dict:
        # Move file
        file_version = self._bucket.copy(
            file_id=source_file_id,
            new_file_name=destination_file_name
        )
        log.info(f"✅ File displaced from ID: {source_file_id} | Original: '{source_file_name}' -> New: '{destination_file_name}'")
        # Delete original file
        self.delete_file_by_id(source_file_id, source_file_name)

        return {
            "name": file_version.file_name,
            "id": file_version.id_,
            "size": file_version.size
        }



    # ==========================================================
    # Files listings
    # ==========================================================
    def list_all_files(self) -> list:
        """Return flat dictionnary of all files and they metadata"""
        all_files = {}
        for file_version, _ in self._bucket.ls(recursive=True):
            all_files[file_version.file_name] = {
                "id": file_version.id_,
                "size": file_version.size,
                "date": file_version.upload_timestamp
            }
        return all_files

    def list_folder(self, target_folder: str) -> list:
        """
        Return flat dictionnary of all files and they metadata
        Distinguish file and folder with type : file or folder
        """
        all_files = {}
        for file_version, folder_name in self._bucket.ls(folder_to_list=target_folder, recursive=False):
            if folder_name:
                all_files[folder_name] = {
                    "type": "folder",
                    "id": None,
                    "size": 0
                }
            else:
                all_files[file_version.file_name] = {
                    "type": "file",
                    "id": file_version.id_,
                    "size": file_version.size,
                    "date": file_version.upload_timestamp
                }
        return all_files
        