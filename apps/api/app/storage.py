"""Object storage for uploaded files. The MinIO client is synchronous, so calls run in a thread."""

import asyncio
import io

from minio import Minio
from minio.error import S3Error

from app.config import Settings


class ObjectStore:
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "ObjectStore":
        client = Minio(
            settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key.get_secret_value(),
            secure=settings.s3_secure,
        )
        return cls(client, settings.s3_bucket)

    async def ensure_bucket(self) -> None:
        def make() -> None:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)

        await asyncio.to_thread(make)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(self._bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, key)
        except S3Error as exc:  # already gone is fine
            if exc.code != "NoSuchKey":
                raise
