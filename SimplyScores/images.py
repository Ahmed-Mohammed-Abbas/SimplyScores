# -*- coding: utf-8 -*-
"""Background image downloader: covers, thumbnails and round avatars.

Images are resized with Pillow (python3-pillow) and written to /tmp so the
GUI only ever loads small, ready-made PNG/JPG files with LoadPixmap (no
ePicLoad decoders to manage). Without Pillow, JPEG/PNG files are stored as-is
and thumbnails are skipped.
"""
import hashlib
import io
import os
import threading
import time
from queue import Queue

from .core import CACHE_DIR, ensure_dir, http_get, log

try:
    from PIL import Image, ImageDraw, ImageOps
    HAVE_PIL = True
    LANCZOS = getattr(Image, "LANCZOS", None) or Image.Resampling.LANCZOS
except Exception:
    HAVE_PIL = False


class ImageCache(object):
    """get() returns a local file path when ready, else queues the download.

    notify(path) is called from the worker thread when a file is ready; the
    caller is responsible for moving that call onto the GUI thread.
    """

    def __init__(self, notify, cache_dir=None):
        self.dir = os.path.join(cache_dir or CACHE_DIR, "img")
        ensure_dir(self.dir)
        self.notify = notify
        self.queue = Queue()
        self.pending = set()
        self.failed = set()
        self.lock = threading.Lock()
        self.stopped = False
        self.thread = None
        self.purge(2 * 86400)

    def purge(self, max_age):
        now = time.time()
        try:
            for name in os.listdir(self.dir):
                path = os.path.join(self.dir, name)
                if now - os.path.getmtime(path) > max_age:
                    os.remove(path)
        except OSError:
            pass

    def _base(self, url, w, h, mode):
        key = hashlib.md5(("%s|%dx%d|%s" % (url, w, h, mode)).encode("utf-8")).hexdigest()
        return os.path.join(self.dir, key)

    def get(self, url, w, h, mode="fill"):
        """mode: 'fill' (rounded thumbnail), 'circle' (avatar), 'cover' (full cover)."""
        if not url:
            return None
        if mode == "fill" and not HAVE_PIL:
            return None
        base = self._base(url, w, h, mode)
        for ext in (".png", ".jpg"):
            if os.path.exists(base + ext):
                return base + ext
        with self.lock:
            if base in self.pending or base in self.failed:
                return None
            self.pending.add(base)
        self.queue.put((url, w, h, mode, base))
        if self.thread is None:
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()
        return None

    def stop(self):
        self.stopped = True
        self.queue.put(None)

    def _run(self):
        while not self.stopped:
            item = self.queue.get()
            if item is None or self.stopped:
                break
            url, w, h, mode, base = item
            path = None
            try:
                data = http_get(url, binary=True, timeout=12,
                                headers={"Accept": "image/jpeg,image/png;q=0.9,image/*;q=0.5"})
                path = self._process(data, w, h, mode, base)
            except Exception as e:
                log("image failed:", url[:70], e)
            with self.lock:
                self.pending.discard(base)
                if not path:
                    self.failed.add(base)
            if path and not self.stopped:
                try:
                    self.notify(path)
                except Exception:
                    pass

    def _save(self, im, path, fmt, **kw):
        tmp = path + ".part"
        im.save(tmp, fmt, **kw)
        os.replace(tmp, path)
        return path

    def _process(self, data, w, h, mode, base):
        if not HAVE_PIL:
            if data[:3] == b"\xff\xd8\xff":
                ext = ".jpg"
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            else:
                return None
            tmp = base + ext + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, base + ext)
            return base + ext

        im = Image.open(io.BytesIO(data))
        im.load()
        if mode == "cover":
            im = im.convert("RGB")
            scale = min(w / float(im.width), h / float(im.height))
            size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
            canvas = Image.new("RGB", (w, h), (0, 0, 0))
            canvas.paste(im.resize(size, LANCZOS), ((w - size[0]) // 2, (h - size[1]) // 2))
            return self._save(canvas, base + ".jpg", "JPEG", quality=85)

        im = ImageOps.fit(im.convert("RGBA"), (w, h), LANCZOS)
        big = Image.new("L", (w * 4, h * 4), 0)
        draw = ImageDraw.Draw(big)
        if mode == "circle":
            draw.ellipse((0, 0, w * 4 - 1, h * 4 - 1), fill=255)
        else:
            draw.rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=max(4, w // 10) * 4, fill=255)
        im.putalpha(big.resize((w, h), LANCZOS))
        if mode == "circle":
            ring = Image.new("RGBA", (w * 4, h * 4), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((2, 2, w * 4 - 3, h * 4 - 3), outline=(255, 255, 255, 255),
                                         width=max(4, w // 12))
            im = Image.alpha_composite(im, ring.resize((w, h), LANCZOS))
        return self._save(im, base + ".png", "PNG")
