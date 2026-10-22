"""Shared response/input encoding. Original image files are never rewritten."""
import asyncio
from pathlib import Path


async def encode_image(source, thumbnail=False, size=384):
    def encode():
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
        from PySide6.QtGui import QImageReader
        buffer = None
        if isinstance(source, Path):
            reader = QImageReader(str(source))
        else:
            buffer = QBuffer()
            buffer.setData(source)
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader = QImageReader(buffer)
        reader.setAutoTransform(True)
        if thumbnail and max(reader.size().width(), reader.size().height()) > size:
            reader.setScaledSize(reader.size().scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return None
        # Copy pixels without passing another browser's PNG prompts/secrets
        # into downloads or the new workflow's input image.
        for key in image.textKeys():
            image.setText(key, '')
        data = QByteArray()
        output = QBuffer(data)
        output.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(output, 'JPEG' if thumbnail else 'PNG', (88 if size > 384 else 80) if thumbnail else -1):
            return None
        return bytes(data)
    return await asyncio.to_thread(encode)
