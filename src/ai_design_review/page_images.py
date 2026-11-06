"""Bounded derived page images; original documents and logical coordinates stay intact."""
from pathlib import Path
import hashlib
import json
import math
import shutil
import threading
import time
import logging

from PIL import Image, ImageOps

VERSION = 'page-images/v1'
MAX_SIDE = 3000
_guard = threading.Lock()


def fingerprint(path):
    stat = path.stat()
    # Cache identity hashes per immutable file revision, not once per request.
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _guard:
        hit = _hashes.get(key)
        if hit: return hit
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    value = digest.hexdigest()
    with _guard:
        if len(_hashes) >= 128: _hashes.clear()
        _hashes[key] = value
    return value


_hashes = {}


def write_json(path, value):
    from .drawing_annotations import atomic_annotation_write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_annotation_write(path, value)


def read_json(path):
    try: return json.loads(path.read_bytes())
    except (OSError, ValueError): return {}


def render_pdf(source, output, prefix, dpi, first_only, *, max_side=MAX_SIDE):
    from pypdf import PdfReader
    from .preprocessing import _render_pdf_uncached
    from .drawing_annotations import annotation_file_lock
    started=time.monotonic(); source_id=fingerprint(source)
    cache=source.parent/'.page_images'/source_id
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    metadata=read_json(output/'.page_metadata.json')
    reader=PdfReader(source)
    paths=[]
    with annotation_file_lock(cache, 'render.lock'):
        for index,page in enumerate(reader.pages[:1] if first_only else reader.pages,1):
            w,h=float(page.mediabox.width),float(page.mediabox.height)
            rotation=int(page.rotation or 0)%360
            if rotation in (90,270): w,h=h,w
            logical=(math.ceil(w*200/72), math.ceil(h*200/72))
            natural=(math.ceil(w*min(dpi,200)/72),math.ceil(h*min(dpi,200)/72))
            side=min(max(natural),max_side) if max_side else max(natural)
            name=f'p{index}-{side}'
            target=cache/f'{name}.png'; info=read_json(cache/f'{name}.json')
            if not target.is_file() or info.get('version')!=VERSION:
                _render_pdf_uncached(source,cache,prefix=name,dpi=dpi,first_page_only=True,max_side=side,page_number=index)
                with Image.open(target) as image: actual=image.size
                info={'version':VERSION,'source_sha256':source_id,'page':index,'rotation':rotation,
                    'width':logical[0],'height':logical[1],'preview_width':actual[0],'preview_height':actual[1],
                    'scale_x':actual[0]/logical[0],'scale_y':actual[1]/logical[1]}
                write_json(cache/f'{name}.json',info)
            destination=output/(f'{prefix}.png' if first_only else f'{prefix}-{index}.png')
            if destination.resolve()!=target.resolve() and (not destination.exists() or read_json(output/'.page_metadata.json').get(destination.name,{}).get('image_version')!=f'{VERSION}:{source_id}:{name}'):
                temporary=destination.with_suffix('.partial.png');shutil.copyfile(target,temporary);temporary.replace(destination)
            metadata[destination.name]={**info,'image_version':f'{VERSION}:{source_id}:{name}'}
            paths.append(str(destination))
        metadata['active_files']=[Path(p).name for p in paths]
        write_json(output/'.page_metadata.json',metadata)
    logging.getLogger(__name__).info('Page render source=%s pages=%s max_side=%s elapsed_ms=%.1f',source_id[:12],len(paths),max_side,(time.monotonic()-started)*1000)
    return paths


def bounded_image(source, destination):
    source_id=fingerprint(source); metadata=read_json(destination.parent/'.page_metadata.json')
    version=f'{VERSION}:{source_id}:png-{MAX_SIDE}'
    if destination.is_file() and metadata.get(destination.name,{}).get('image_version')==version: return str(destination)
    with Image.open(source) as original:
        image=ImageOps.exif_transpose(original).copy(); logical=image.size
        image.thumbnail((MAX_SIDE,MAX_SIDE),Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_suffix('.partial.png');image.save(temporary,'PNG');temporary.replace(destination)
        actual=image.size
    metadata[destination.name]={'version':VERSION,'source_sha256':source_id,'page':1,'rotation':0,'width':logical[0],'height':logical[1],
        'preview_width':actual[0],'preview_height':actual[1],'scale_x':actual[0]/logical[0],'scale_y':actual[1]/logical[1],'image_version':version}
    metadata['active_files']=[destination.name];write_json(destination.parent/'.page_metadata.json',metadata)
    return str(destination)


def qwen_images(paths, output):
    output.mkdir(parents=True,exist_ok=True);result=[]
    for index,source in enumerate(map(Path,paths),1):
        version=f'{VERSION}:{fingerprint(source)}:jpeg90'
        target=output/f'input-{index}.jpg'; marker=output/f'input-{index}.json'
        if not target.is_file() or read_json(marker).get('image_version')!=version:
            with Image.open(source) as original:
                image=ImageOps.exif_transpose(original).convert('RGBA')
                background=Image.new('RGBA',image.size,'white');background.alpha_composite(image);image=background.convert('RGB');image.thumbnail((MAX_SIDE,MAX_SIDE),Image.Resampling.LANCZOS)
                while True:
                    image.save(target,'JPEG',quality=90)
                    if target.stat().st_size<=8*1024**2:break
                    image=image.resize((max(1,int(image.width*.85)),max(1,int(image.height*.85))),Image.Resampling.LANCZOS)
                write_json(marker,{'image_version':version,'width':image.width,'height':image.height,'bytes':target.stat().st_size})
        result.append(target)
    return result


def render_region(source, page, region, *, max_side=1800, dpi=300):
    """Render only the requested rectangle, never a huge full-page intermediate."""
    import pymupdf
    with pymupdf.open(source) as document:
        original=document[page-1];rect=original.rect
        clip=pymupdf.Rect(region[0]*rect.width,region[1]*rect.height,region[2]*rect.width,region[3]*rect.height)
        scale=min(dpi/72,max_side/max(clip.width,clip.height))
        pix=original.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=clip,alpha=False)
        return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
