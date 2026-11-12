"""
Online open-source Fritzing library search, SVG/FZP compatibility validator, and importer.
Searches public GitHub Fritzing repositories (Fritzing Core, Adafruit, SparkFun), validates
that parts fit a 2.54 mm (0.1 in) perfboard hole grid before showing results, and downloads
verified parts on demand when dragged/placed into the viewport.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Callable

from app.components.fritzing_part import DOWNLOADED_PARTS_DIR, FritzingComponentDef
from app.models.component_def import OffGridPinDef, PinDef

FRITZING_LIBRARIES: tuple[tuple[str, str, str, str], ...] = (
    # (Display name, owner/repo, branch, kind: 'fzpz' | 'core_fzp')
    ("Adafruit", "adafruit/Fritzing-Library", "master", "fzpz"),
    ("SparkFun", "sparkfun/Fritzing_Parts", "main", "fzpz"),
    ("Fritzing Core", "fritzing/fritzing-parts", "main", "core_fzp"),
)

_INDEX_CACHE_PATH = os.path.join(DOWNLOADED_PARTS_DIR, ".index_cache.json")
_INDEX_CACHE_TTL_SEC = 24 * 3600
_MM_PER_HOLE = 2.54
_GRID_TOLERANCE_MM = 0.42

_LENGTH_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)\s*$"
)
_TRANSFORM_FUNC_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_PATH_TOK_RE = re.compile(
    r"[MmZzLlHhVvCcSsQqTtAa]|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
)


@dataclass(frozen=True)
class FritzingCatalogEntry:
    source_name: str
    repo: str
    branch: str
    kind: str  # 'fzpz' or 'core_fzp'
    path: str
    display_name: str
    type_id: str


_INDEX_LOCK = threading.Lock()
_MEMORY_CATALOG: list[FritzingCatalogEntry] | None = None


def _http_get_bytes(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PerfBoardMaker-FritzingSearch",
            "Accept": "application/vnd.github+json, application/octet-stream, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if getattr(resp, "status", 200) != 200:
            raise RuntimeError(f"HTTP {getattr(resp, 'status', 'error')} for {url}")
        return resp.read()


def _make_type_id(repo: str, path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()[:36] or "part"
    digest = hashlib.sha1(f"{repo}:{path}".encode("utf-8")).hexdigest()[:8]
    return f"fritzing_{slug}_{digest}"


def _clean_display_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    # Remove trailing Fritzing hash suffixes like __a1b2c3d4..._12
    stem = re.sub(r"__[0-9a-fA-F]{16,}(?:_\d+)?$", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or os.path.basename(path)


def get_fritzing_catalog(force_refresh: bool = False) -> list[FritzingCatalogEntry]:
    """Loads or refreshes the recursive file index from free GitHub Fritzing repositories."""
    global _MEMORY_CATALOG
    with _INDEX_LOCK:
        if _MEMORY_CATALOG is not None and not force_refresh:
            return _MEMORY_CATALOG

        if not force_refresh and os.path.isfile(_INDEX_CACHE_PATH):
            try:
                with open(_INDEX_CACHE_PATH, "r", encoding="utf-8") as cf:
                    cached = json.load(cf)
                if time.time() - float(cached.get("timestamp", 0)) < _INDEX_CACHE_TTL_SEC:
                    entries = [
                        FritzingCatalogEntry(**item)
                        for item in cached.get("entries", [])
                    ]
                    if entries:
                        _MEMORY_CATALOG = entries
                        return entries
            except Exception:
                pass

        entries: list[FritzingCatalogEntry] = []

        def _fetch_repo_tree(lib_tuple):
            source_name, repo, branch, kind = lib_tuple
            url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
            raw = _http_get_bytes(url, timeout=10.0)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            local_entries: list[FritzingCatalogEntry] = []
            for node in data.get("tree", []):
                if node.get("type") != "blob":
                    continue
                path = str(node.get("path", ""))
                lower = path.lower()
                if kind == "fzpz":
                    if not lower.endswith(".fzpz"):
                        continue
                else:
                    if not (lower.startswith("core/") and lower.endswith(".fzp")):
                        continue
                local_entries.append(
                    FritzingCatalogEntry(
                        source_name=source_name,
                        repo=repo,
                        branch=branch,
                        kind=kind,
                        path=path,
                        display_name=_clean_display_name(path),
                        type_id=_make_type_id(repo, path),
                    )
                )
            return local_entries

        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = [pool.submit(_fetch_repo_tree, lib) for lib in FRITZING_LIBRARIES]
            for fut in as_completed(futs):
                try:
                    entries.extend(fut.result())
                except Exception:
                    continue

        if entries:
            try:
                os.makedirs(DOWNLOADED_PARTS_DIR, exist_ok=True)
                with open(_INDEX_CACHE_PATH, "w", encoding="utf-8") as cf:
                    json.dump(
                        {
                            "timestamp": time.time(),
                            "entries": [e.__dict__ for e in entries],
                        },
                        cf,
                    )
            except Exception:
                pass
            _MEMORY_CATALOG = entries
        return entries


def search_catalog_candidates(
    query: str,
    exclude_type_ids: set[str] | None = None,
    limit: int = 12,
) -> list[FritzingCatalogEntry]:
    """Matches query tokens locally against the cached Fritzing catalog and ranks best fits."""
    tokens = [tok for tok in re.split(r"[\s_\-]+", query.strip().lower()) if tok]
    if not tokens:
        return []

    catalog = get_fritzing_catalog()
    excluded = exclude_type_ids or set()
    scored: list[tuple[int, int, FritzingCatalogEntry]] = []

    for entry in catalog:
        if entry.type_id in excluded:
            continue
        hay_name = entry.display_name.lower()
        hay_path = entry.path.lower()
        if all(tok in hay_name or tok in hay_path for tok in tokens):
            score = 0
            if hay_name.startswith(" ".join(tokens)):
                score -= 40
            if all(tok in hay_name for tok in tokens):
                score -= 20
            if entry.kind == "fzpz":
                score -= 10  # Adafruit/SparkFun breakouts are well-curated .fzpz packages
            scored.append((score, len(hay_name), entry))

    scored.sort(key=lambda item: (item[0], item[1], item[2].display_name.lower()))
    return [item[2] for item in scored[:limit]]


def search_fritzing_forum_candidates(
    query: str,
    exclude_type_ids: set[str] | None = None,
    cancel_event: threading.Event | None = None,
    limit: int = 8,
) -> list[FritzingCatalogEntry]:
    """
    Searches forum.fritzing.org (prioritizing parts-submit category 23 and parts-help)
    for topics with .fzpz part attachments.
    """
    q = query.strip()
    if len(q) < 2 or (cancel_event is not None and cancel_event.is_set()):
        return []

    excluded = exclude_type_ids or set()
    search_url = f"https://forum.fritzing.org/search.json?q={urllib.parse.quote(q)}"
    try:
        raw = _http_get_bytes(search_url, timeout=6.0)
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError):
        return []

    topics = data.get("topics") or []
    if not topics:
        return []

    # Prioritize Parts Submit (23) and Parts Help (9) categories
    def _topic_rank(t: dict) -> tuple[int, int]:
        cat_id = t.get("category_id")
        if cat_id == 23:
            return (0, int(t.get("id", 0)))
        if cat_id == 9:
            return (1, int(t.get("id", 0)))
        return (2, int(t.get("id", 0)))

    topics = sorted(topics, key=_topic_rank)[:6]
    entries: list[FritzingCatalogEntry] = []
    seen_urls: set[str] = set()

    def _fetch_topic_fzpz(topic: dict) -> list[FritzingCatalogEntry]:
        if cancel_event is not None and cancel_event.is_set():
            return []
        tid = topic.get("id")
        if not tid:
            return []
        t_title = (topic.get("title") or f"Forum Part {tid}").strip()
        topic_url = f"https://forum.fritzing.org/t/{tid}.json"
        try:
            t_raw = _http_get_bytes(topic_url, timeout=6.0)
            t_data = json.loads(t_raw.decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError):
            return []

        found: list[FritzingCatalogEntry] = []
        posts = (t_data.get("post_stream") or {}).get("posts") or []
        for post in posts:
            cooked = post.get("cooked") or ""
            for href in re.findall(r'href=["\']([^"\']*\.fzpz[^"\']*)["\']', cooked, re.I):
                full_url = urllib.parse.urljoin("https://forum.fritzing.org", href)
                digest = hashlib.sha1(full_url.encode("utf-8")).hexdigest()[:10]
                type_id = f"fritzing_forum_{digest}"
                if type_id in excluded:
                    continue
                fname = os.path.basename(urllib.parse.urlparse(full_url).path)
                disp = _clean_display_name(fname) if fname and not fname.startswith("eqt") else t_title
                if not disp or len(disp) < 3:
                    disp = t_title
                found.append(
                    FritzingCatalogEntry(
                        source_name="Fritzing Forum",
                        repo="forum.fritzing.org",
                        branch="",
                        kind="forum_fzpz",
                        path=full_url,
                        display_name=t_title if t_title else disp,
                        type_id=type_id,
                    )
                )
        return found

    with ThreadPoolExecutor(max_workers=4) as pool:
        for res in pool.map(_fetch_topic_fzpz, topics):
            for entry in res:
                if entry.path in seen_urls:
                    continue
                seen_urls.add(entry.path)
                entries.append(entry)
                if len(entries) >= limit:
                    return entries
    return entries


# --- SVG PHYSICAL UNITS & 2D TRANSFORM ENGINE ---

def _parse_length_mm(raw: str | None) -> float | None:
    if not raw:
        return None
    m = _LENGTH_RE.match(raw)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "mm":
        return val
    if unit == "cm":
        return val * 10.0
    if unit == "in":
        return val * 25.4
    if unit == "pt":
        return val * 25.4 / 72.0
    if unit == "pc":
        return val * 25.4 / 6.0
    if unit in ("", "px"):
        return val * 25.4 / 96.0
    return None


def _mul_mat(m1: tuple[float, ...], m2: tuple[float, ...]) -> tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply_mat(m: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_transform(attr: str | None) -> tuple[float, ...]:
    mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not attr:
        return mat
    for fn, args_str in _TRANSFORM_FUNC_RE.findall(attr):
        nums = [float(x) for x in _NUM_RE.findall(args_str)]
        fn_l = fn.lower()
        t_mat = None
        if fn_l == "matrix" and len(nums) >= 6:
            t_mat = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif fn_l == "translate" and len(nums) >= 1:
            tx = nums[0]
            ty = nums[1] if len(nums) >= 2 else 0.0
            t_mat = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif fn_l == "scale" and len(nums) >= 1:
            sx = nums[0]
            sy = nums[1] if len(nums) >= 2 else sx
            t_mat = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif fn_l == "rotate" and len(nums) >= 1:
            rad = math.radians(nums[0])
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                t_mat = _mul_mat(
                    (1.0, 0.0, 0.0, 1.0, cx, cy),
                    _mul_mat((cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, -cx, -cy)),
                )
            else:
                t_mat = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        elif fn_l == "skewx" and len(nums) >= 1:
            t_mat = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif fn_l == "skewy" and len(nums) >= 1:
            t_mat = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)

        if t_mat is not None:
            mat = _mul_mat(mat, t_mat)
    return mat


def _path_local_center(d_str: str) -> tuple[float, float] | None:
    toks = _PATH_TOK_RE.findall(d_str or "")
    if not toks:
        return None
    idx = 0
    cmd = ""
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    xs: list[float] = []
    ys: list[float] = []

    def _is_cmd(t: str) -> bool:
        return len(t) == 1 and t.isalpha()

    while idx < len(toks):
        if _is_cmd(toks[idx]):
            cmd = toks[idx]
            idx += 1
            if cmd in ("Z", "z"):
                cx, cy = sx, sy
                continue
        if not cmd:
            break

        if cmd in ("M", "m", "L", "l", "T", "t"):
            if idx + 1 >= len(toks):
                break
            x = float(toks[idx]); y = float(toks[idx + 1]); idx += 2
            if cmd.islower():
                cx += x; cy += y
            else:
                cx, cy = x, y
            if cmd in ("M", "m"):
                sx, sy = cx, cy
                cmd = "l" if cmd == "m" else "L"
            xs.append(cx); ys.append(cy)
        elif cmd in ("H", "h"):
            x = float(toks[idx]); idx += 1
            cx = (cx + x) if cmd == "h" else x
            xs.append(cx); ys.append(cy)
        elif cmd in ("V", "v"):
            y = float(toks[idx]); idx += 1
            cy = (cy + y) if cmd == "v" else y
            xs.append(cx); ys.append(cy)
        elif cmd in ("C", "c"):
            if idx + 5 >= len(toks):
                break
            pts = [float(toks[idx + k]) for k in range(6)]
            idx += 6
            if cmd == "c":
                x1, y1, x2, y2, x, y = pts
                xs.extend((cx + x1, cx + x2, cx + x))
                ys.extend((cy + y1, cy + y2, cy + y))
                cx += x; cy += y
            else:
                xs.extend((pts[0], pts[2], pts[4]))
                ys.extend((pts[1], pts[3], pts[5]))
                cx, cy = pts[4], pts[5]
        elif cmd in ("S", "s", "Q", "q"):
            if idx + 3 >= len(toks):
                break
            pts = [float(toks[idx + k]) for k in range(4)]
            idx += 4
            if cmd.islower():
                xs.extend((cx + pts[0], cx + pts[2]))
                ys.extend((cy + pts[1], cy + pts[3]))
                cx += pts[2]; cy += pts[3]
            else:
                xs.extend((pts[0], pts[2]))
                ys.extend((pts[1], pts[3]))
                cx, cy = pts[2], pts[3]
        elif cmd in ("A", "a"):
            if idx + 6 >= len(toks):
                break
            x = float(toks[idx + 5]); y = float(toks[idx + 6]); idx += 7
            if cmd == "a":
                cx += x; cy += y
            else:
                cx, cy = x, y
            xs.append(cx); ys.append(cy)
        else:
            idx += 1

    if not xs:
        return None
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _element_own_center(el: ET.Element, mat: tuple[float, ...]) -> tuple[float, float] | None:
    tag = el.tag.split("}")[-1].lower()
    if tag in ("circle", "ellipse"):
        cx = float(el.get("cx") or 0.0)
        cy = float(el.get("cy") or 0.0)
        return _apply_mat(mat, cx, cy)
    if tag == "rect":
        x = float(el.get("x") or 0.0)
        y = float(el.get("y") or 0.0)
        w = float(el.get("width") or 0.0)
        h = float(el.get("height") or 0.0)
        return _apply_mat(mat, x + w / 2.0, y + h / 2.0)
    if tag == "line":
        x1 = float(el.get("x1") or 0.0)
        y1 = float(el.get("y1") or 0.0)
        x2 = float(el.get("x2") or 0.0)
        y2 = float(el.get("y2") or 0.0)
        return _apply_mat(mat, (x1 + x2) / 2.0, (y1 + y2) / 2.0)
    if tag in ("polygon", "polyline"):
        nums = [float(n) for n in _NUM_RE.findall(el.get("points") or "")]
        if len(nums) >= 2:
            pxs = nums[0::2]
            pys = nums[1::2]
            lx = (min(pxs) + max(pxs)) / 2.0
            ly = (min(pys) + max(pys)) / 2.0
            return _apply_mat(mat, lx, ly)
    if tag == "path":
        pt = _path_local_center(el.get("d") or "")
        if pt is not None:
            return _apply_mat(mat, pt[0], pt[1])
    return None


def _resolve_element_center(el: ET.Element, mat: tuple[float, ...]) -> tuple[float, float] | None:
    direct = _element_own_center(el, mat)
    if direct is not None:
        return direct

    # Container group (e.g. <g id="connector0pin">): collect child shapes
    child_pts: list[tuple[float, float]] = []

    def _walk_children(node: ET.Element, cur_mat: tuple[float, ...]):
        for child in node:
            cmat = _mul_mat(cur_mat, _parse_transform(child.get("transform")))
            pt = _element_own_center(child, cmat)
            if pt is not None:
                child_pts.append(pt)
            else:
                _walk_children(child, cmat)

    _walk_children(el, mat)
    if not child_pts:
        return None
    xs = [p[0] for p in child_pts]
    ys = [p[1] for p in child_pts]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _index_svg_elements(sroot: ET.Element) -> dict[str, tuple[ET.Element, tuple[float, ...]]]:
    id_map: dict[str, tuple[ET.Element, tuple[float, ...]]] = {}

    def _walk(node: ET.Element, parent_mat: tuple[float, ...]):
        mat = _mul_mat(parent_mat, _parse_transform(node.get("transform")))
        el_id = node.get("id")
        if el_id:
            id_map[el_id] = (node, mat)
        for child in node:
            _walk(child, mat)

    _walk(sroot, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return id_map


def _has_explicit_physical_unit(raw: str | None) -> bool:
    if not raw:
        return False
    m = _LENGTH_RE.match(raw)
    if not m:
        return False
    return m.group(2).lower() in ("mm", "cm", "in", "pt", "pc")


def _parse_svg_physical_frame(sroot: ET.Element) -> tuple[float, float, float, float, float, float, bool] | None:
    """
    Returns (vb_x, vb_y, scale_x_mm, scale_y_mm, width_mm, height_mm, has_explicit_units)
    mapping transformed SVG user coordinates -> physical millimeters relative to top-left of SVG.
    When has_explicit_units is False (px or unitless), scale assumes 96 DPI initially and may be
    tested against 72 DPI (Illustrator) and 90 DPI (legacy Inkscape).
    """
    w_raw = sroot.get("width")
    h_raw = sroot.get("height")
    w_mm = _parse_length_mm(w_raw)
    h_mm = _parse_length_mm(h_raw)
    explicit_units = _has_explicit_physical_unit(w_raw) and _has_explicit_physical_unit(h_raw)

    vb_str = sroot.get("viewBox")
    if vb_str:
        nums = [float(x) for x in _NUM_RE.findall(vb_str)]
        if len(nums) != 4 or nums[2] <= 0 or nums[3] <= 0:
            return None
        vb_x, vb_y, vb_w, vb_h = nums
        if w_mm is not None and h_mm is not None and w_mm > 0 and h_mm > 0:
            sx = w_mm / vb_w
            sy = h_mm / vb_h
        else:
            sx = sy = 25.4 / 96.0
            w_mm = vb_w * sx
            h_mm = vb_h * sy
        return (vb_x, vb_y, sx, sy, w_mm, h_mm, explicit_units)

    if w_mm is not None and h_mm is not None and w_mm > 0 and h_mm > 0:
        sx = sy = 25.4 / 96.0
        return (0.0, 0.0, sx, sy, w_mm, h_mm, explicit_units)
    return None


def _classify_pin_type(name: str, conn_type: str) -> str:
    n = name.upper()
    if any(k in n for k in ("GND", "VSS", "0V", "GROUND")):
        return "ground"
    if any(k in n for k in ("VCC", "VDD", "VIN", "V+", "+V", "3V", "3.3V", "5V", "12V")):
        return "power"
    if conn_type.lower() == "pad":
        return "passive"
    return "io"


_MAX_LOCAL_FILE_BYTES = 25 * 1024 * 1024


def _read_fzpz_bytes(data: bytes) -> tuple[bytes, bytes]:
    """Extracts (.fzp bytes, breadboard .svg bytes) from .fzpz archive bytes."""
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        infos = {info.filename: info for info in zf.infolist()}
        names = list(infos.keys())
        fzp_names = [n for n in names if n.lower().endswith(".fzp")]
        if not fzp_names:
            raise ValueError("Missing .fzp inside .fzpz archive")
        fzp_name = fzp_names[0]
        if infos[fzp_name].file_size > _MAX_LOCAL_FILE_BYTES:
            raise ValueError("Fritzing .fzp entry is too large")
        fzp_bytes = zf.read(fzp_name)
        fzp_root = ET.fromstring(fzp_bytes)
        bb_layers = fzp_root.find("./views/breadboardView/layers")
        if bb_layers is None or not bb_layers.get("image"):
            raise ValueError("Part has no breadboard view")
        bb_img = bb_layers.get("image", "")
        expected_svg_name = "svg." + bb_img.replace("/", ".")
        svg_name = None
        if expected_svg_name in infos:
            svg_name = expected_svg_name
        else:
            base_name = os.path.basename(bb_img).lower()
            matches = [
                n for n in names
                if n.lower().endswith(".svg") and (
                    n.lower().endswith(base_name) or "breadboard" in n.lower()
                )
            ]
            if matches:
                svg_name = matches[0]
        if svg_name is None:
            raise ValueError("Missing breadboard .svg inside .fzpz archive")
        if infos[svg_name].file_size > _MAX_LOCAL_FILE_BYTES:
            raise ValueError("Breadboard .svg entry is too large")
        return fzp_bytes, zf.read(svg_name)


def _download_candidate_files(entry: FritzingCatalogEntry) -> tuple[bytes, bytes]:
    """Downloads (.fzp bytes, breadboard .svg bytes) for a FritzingCatalogEntry."""
    if entry.kind == "forum_fzpz":
        data = _http_get_bytes(entry.path, timeout=10.0)
        return _read_fzpz_bytes(data)

    encoded_path = urllib.parse.quote(entry.path, safe="/")
    raw_url = f"https://raw.githubusercontent.com/{entry.repo}/{entry.branch}/{encoded_path}"
    data = _http_get_bytes(raw_url, timeout=10.0)

    if entry.kind == "fzpz":
        return _read_fzpz_bytes(data)

    # core_fzp
    fzp_bytes = data
    fzp_root = ET.fromstring(fzp_bytes)
    bb_layers = fzp_root.find("./views/breadboardView/layers")
    if bb_layers is None or not bb_layers.get("image"):
        raise ValueError("Core part has no breadboard view")
    bb_img = bb_layers.get("image", "").lstrip("/")
    svg_rel = urllib.parse.quote(f"svg/core/{bb_img}", safe="/")
    svg_url = f"https://raw.githubusercontent.com/{entry.repo}/{entry.branch}/{svg_rel}"
    svg_bytes = _http_get_bytes(svg_url, timeout=10.0)
    return fzp_bytes, svg_bytes


def parse_and_validate_fritzing_part(
    entry: FritzingCatalogEntry,
    fzp_bytes: bytes,
    svg_bytes: bytes,
) -> tuple[FritzingComponentDef | None, str | None]:
    """
    Validates strict 2.54 mm PerfBoard compatibility for a Fritzing part.
    Returns (FritzingComponentDef, None) if compatible, else (None, reason).
    """
    try:
        fzp_root = ET.fromstring(fzp_bytes)
        svg_root = ET.fromstring(svg_bytes)
    except ET.ParseError as exc:
        return None, f"Invalid XML/SVG: {exc}"

    if svg_root.tag.split("}")[-1].lower() != "svg":
        return None, "Not a valid SVG document"

    frame = _parse_svg_physical_frame(svg_root)
    if frame is None:
        return None, "SVG lacks physical dimensions"
    vb_x, vb_y, base_sx_mm, base_sy_mm, base_w_mm, base_h_mm, explicit_units = frame

    id_map = _index_svg_elements(svg_root)

    # Extract bus equivalence groups (e.g. parallel side STEMMA/Qwiic sockets)
    bus_adj: dict[str, set[str]] = {}
    for bus in fzp_root.findall("./buses/bus"):
        members = [m.get("connectorId") for m in bus.findall("nodeMember") if m.get("connectorId")]
        mset = set(members)
        for cid in members:
            bus_adj.setdefault(cid, set()).update(mset)

    vb_connectors: list[tuple[str, str, str, str, float, float]] = []
    for conn in fzp_root.findall("./connectors/connector"):
        cid = conn.get("id") or ""
        cname = (conn.get("name") or cid or "Pin").strip()
        ctype = (conn.get("type") or "male").strip().lower()
        cdesc = (conn.findtext("description") or "").strip()
        bb_p = conn.find("./views/breadboardView/p")
        if bb_p is None:
            continue

        sid = bb_p.get("svgId")
        tid = bb_p.get("terminalId")

        center_vb = None
        if tid and tid in id_map:
            el_t, mat_t = id_map[tid]
            center_vb = _resolve_element_center(el_t, mat_t)
        if center_vb is None and sid and sid in id_map:
            el_s, mat_s = id_map[sid]
            center_vb = _resolve_element_center(el_s, mat_s)
        if center_vb is None:
            continue

        vb_connectors.append((cid, cname, _classify_pin_type(cname, ctype), cdesc, center_vb[0], center_vb[1]))

def _evaluate_alignment(
    raw_conns: list[tuple[str, str, str, str, float, float]],
    bus_adj: dict[str, set[str]],
) -> tuple[tuple[int, int], dict[int, tuple[int, int]], list[int]]:
    """Finds the anchor connector that maximizes 2.54 mm grid-aligned pins."""
    best: tuple[tuple[int, int], dict[int, tuple[int, int]], list[int]] | None = None
    for anchor in raw_conns:
        ax, ay = anchor[4], anchor[5]
        aligned: dict[int, tuple[int, int]] = {}
        for j, item in enumerate(raw_conns):
            gx_f = (item[4] - ax) / _MM_PER_HOLE
            gy_f = (item[5] - ay) / _MM_PER_HOLE
            gx = round(gx_f)
            gy = round(gy_f)
            err_mm = max(abs(gx_f - gx) * _MM_PER_HOLE, abs(gy_f - gy) * _MM_PER_HOLE)
            if err_mm <= _GRID_TOLERANCE_MM:
                aligned[j] = (gx, gy)

        aligned_cids = {raw_conns[j][0] for j in aligned}
        unbused = [
            j for j, item in enumerate(raw_conns)
            if j not in aligned and not (bus_adj.get(item[0], set()) & aligned_cids)
        ]
        score = (-len(unbused), len(aligned))
        if best is None or score > best[0]:
            best = (score, aligned, unbused)
    assert best is not None
    return best


def _has_hole_collision(
    raw_conns: list[tuple[str, str, str, str, float, float]],
    aligned: dict[int, tuple[int, int]],
    bus_adj: dict[str, set[str]],
) -> bool:
    if not aligned:
        return False
    kept = sorted(aligned.keys())
    base_gx, base_gy = aligned[kept[0]]
    occupied: dict[tuple[int, int], str] = {}
    for j in kept:
        cid = raw_conns[j][0]
        hole = (aligned[j][0] - base_gx, aligned[j][1] - base_gy)
        if hole in occupied:
            if occupied[hole] in bus_adj.get(cid, set()):
                continue
            return True
        occupied[hole] = cid
    return False


def _find_best_scaled_alignment(
    raw_conns: list[tuple[str, str, str, str, float, float]],
    w_mm: float,
    h_mm: float,
    bus_adj: dict[str, set[str]],
    orig_aligned_count: int,
    orig_unbused_count: int,
) -> tuple[float, list[tuple[str, str, str, str, float, float]], float, float, dict[int, tuple[int, int]]] | None:
    """Checks if a uniform scale factor aligns unaligned pins to the 2.54 mm grid."""
    if len(raw_conns) < 2:
        return None

    candidate_scales: set[float] = {10.0, 2.54, 96.0 / 25.4, 72.0 / 25.4, 90.0 / 25.4, 96.0 / 72.0, 2.0, 0.5, 0.1}
    deltas: list[float] = []
    for i in range(len(raw_conns)):
        x1, y1 = raw_conns[i][4], raw_conns[i][5]
        for j in range(i + 1, len(raw_conns)):
            dx = abs(raw_conns[j][4] - x1)
            dy = abs(raw_conns[j][5] - y1)
            if dx > 0.02:
                deltas.append(dx)
            if dy > 0.02:
                deltas.append(dy)
    for d in sorted(set(round(v, 4) for v in deltas))[:10]:
        candidate_scales.add(_MM_PER_HOLE / d)
        candidate_scales.add((2.0 * _MM_PER_HOLE) / d)

    best: tuple[tuple[int, int, float], float, list[tuple[str, str, str, str, float, float]], float, float, dict[int, tuple[int, int]]] | None = None
    for s in candidate_scales:
        if not (0.15 <= s <= 60.0) or abs(s - 1.0) < 0.04:
            continue
        sw, sh = w_mm * s, h_mm * s
        if not (5.0 <= max(sw, sh) <= 350.0):
            continue
        scaled_conns = [(*item[:4], item[4] * s, item[5] * s) for item in raw_conns]
        score, aligned, unbused = _evaluate_alignment(scaled_conns, bus_adj)
        if len(aligned) < 2:
            continue
        if len(aligned) <= orig_aligned_count and len(unbused) >= orig_unbused_count:
            continue
        if _has_hole_collision(scaled_conns, aligned, bus_adj):
            continue
        rank = (-len(unbused), len(aligned), -abs(math.log(s)))
        if best is None or rank > best[0]:
            best = (rank, s, scaled_conns, sw, sh, aligned)

    if best is None:
        return None
    return best[1], best[2], best[3], best[4], best[5]


def _build_fritzing_component_def(
    entry: FritzingCatalogEntry,
    fzp_root: ET.Element,
    svg_bytes: bytes,
    raw_connectors: list[tuple[str, str, str, str, float, float]],
    svg_w_mm: float,
    svg_h_mm: float,
    best_aligned: dict[int, tuple[int, int]],
    bus_adj: dict[str, set[str]],
    scale_factor: float | None = None,
) -> FritzingComponentDef:
    total_conns = len(raw_connectors)
    use_aligned = total_conns == 1 or len(best_aligned) >= 2
    final_items: list[tuple[tuple[str, str, str, str, float, float], int, int]] = []
    if use_aligned and best_aligned:
        kept_indices = sorted(best_aligned.keys())
        occupied_holes: dict[tuple[int, int], str] = {}
        base_gx, base_gy = best_aligned[kept_indices[0]]
        anchor_x_mm = raw_connectors[kept_indices[0]][4]
        anchor_y_mm = raw_connectors[kept_indices[0]][5]

        for j in kept_indices:
            item = raw_connectors[j]
            cid = item[0]
            gx = best_aligned[j][0] - base_gx
            gy = best_aligned[j][1] - base_gy
            hole = (gx, gy)
            if hole in occupied_holes:
                other_cid = occupied_holes[hole]
                if other_cid in bus_adj.get(cid, set()):
                    continue
                use_aligned = False
                final_items.clear()
                break
            occupied_holes[hole] = cid
            final_items.append((item, gx, gy))

    if use_aligned and final_items:
        pins = [
            PinDef(
                name=entry_item[0][1],
                grid_x=entry_item[1],
                grid_y=entry_item[2],
                description=entry_item[0][3],
                pin_type=entry_item[0][2],
            )
            for entry_item in final_items
        ]
        off_grid_indices = [j for j in range(len(raw_connectors)) if j not in best_aligned]
    else:
        pins = []
        anchor_x_mm = raw_connectors[0][4]
        anchor_y_mm = raw_connectors[0][5]
        off_grid_indices = list(range(len(raw_connectors)))

    off_grid_pins: list[OffGridPinDef] = []
    seen_off_grid_pos: set[tuple[float, float]] = set()
    for j in off_grid_indices:
        item = raw_connectors[j]
        ox = round((item[4] - anchor_x_mm) / _MM_PER_HOLE, 4)
        oy = round((item[5] - anchor_y_mm) / _MM_PER_HOLE, 4)
        key = (round(ox, 2), round(oy, 2))
        if key in seen_off_grid_pos:
            continue
        seen_off_grid_pos.add(key)
        off_grid_pins.append(
            OffGridPinDef(
                name=item[1],
                offset_x=ox,
                offset_y=oy,
                description=item[3],
                pin_type=item[2],
            )
        )
    off_grid_pins.sort(key=lambda op: (op.offset_y, op.offset_x, op.name))

    title = (fzp_root.findtext("title") or entry.display_name).strip()
    if scale_factor is not None:
        title = f"{title} ({scale_factor:.2f}x)"
    label = (fzp_root.findtext("label") or "U").strip() or "U"
    author = (fzp_root.findtext("author") or entry.source_name).strip()
    url = (fzp_root.findtext("url") or (f"https://github.com/{entry.repo}" if entry.repo else "")).strip()
    raw_desc = (fzp_root.findtext("description") or "").strip()
    clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
    tags = [t.text.strip() for t in fzp_root.findall("./tags/tag") if t.text and t.text.strip()]
    for extra in (entry.source_name.lower(), "fritzing", "svg"):
        if extra not in tags:
            tags.append(extra)

    attr_line = f"Source: {entry.source_name} ({author})"
    if scale_factor is not None:
        attr_line += f"\nScaled {scale_factor:.2f}x for 2.54 mm perfboard alignment."
    if not pins and off_grid_pins:
        attr_line += (
            f"\nUnaligned part ({len(off_grid_pins)} pins): pins cannot be aligned with the "
            f"perfboard and are only connectable via jumpers."
        )
    elif off_grid_pins:
        attr_line += f"\nJumper-only off-grid pins ({len(off_grid_pins)}): cannot plug into holes; connect via jumper wires."
    full_desc = f"{clean_desc}\n\n{attr_line}".strip() if clean_desc else attr_line

    type_id = f"{entry.type_id}_s{int(round(scale_factor * 100))}" if scale_factor is not None else entry.type_id
    return FritzingComponentDef(
        type_id=type_id,
        name=title,
        category=f"Online ({entry.source_name})",
        default_label=label[:6],
        description=full_desc,
        pins=pins,
        svg_bytes=svg_bytes,
        anchor_x_mm=anchor_x_mm,
        anchor_y_mm=anchor_y_mm,
        svg_width_mm=svg_w_mm,
        svg_height_mm=svg_h_mm,
        tags=tags,
        source_info={
            "source_name": entry.source_name,
            "repo": entry.repo,
            "branch": entry.branch,
            "path": entry.path,
            "author": author,
            "url": url,
            "license": "CC BY-SA" if entry.repo else "Unknown",
        },
        is_remote_preview=True,
        off_grid_pins=off_grid_pins,
    )


def parse_fritzing_part_options(
    entry: FritzingCatalogEntry,
    fzp_bytes: bytes,
    svg_bytes: bytes,
) -> tuple[FritzingComponentDef | None, FritzingComponentDef | None, float | None, str | None]:
    """
    Parses a Fritzing part with relaxed compatibility checks and also checks whether
    a uniform scale factor aligns unaligned pins to the 2.54 mm grid.
    Returns (orig_comp_def, scaled_comp_def, scale_factor, reason).
    """
    try:
        fzp_root = ET.fromstring(fzp_bytes)
        svg_root = ET.fromstring(svg_bytes)
    except ET.ParseError as exc:
        return None, None, None, f"Invalid XML/SVG: {exc}"

    if svg_root.tag.split("}")[-1].lower() != "svg":
        return None, None, None, "Not a valid SVG document"

    frame = _parse_svg_physical_frame(svg_root)
    if frame is None:
        return None, None, None, "SVG lacks physical dimensions"
    vb_x, vb_y, base_sx_mm, base_sy_mm, base_w_mm, base_h_mm, explicit_units = frame

    id_map = _index_svg_elements(svg_root)

    bus_adj: dict[str, set[str]] = {}
    for bus in fzp_root.findall("./buses/bus"):
        members = [m.get("connectorId") for m in bus.findall("nodeMember") if m.get("connectorId")]
        mset = set(members)
        for cid in members:
            bus_adj.setdefault(cid, set()).update(mset)

    vb_connectors: list[tuple[str, str, str, str, float, float]] = []
    for conn in fzp_root.findall("./connectors/connector"):
        cid = conn.get("id") or ""
        cname = (conn.get("name") or cid or "Pin").strip()
        ctype = (conn.get("type") or "male").strip().lower()
        cdesc = (conn.findtext("description") or "").strip()
        bb_p = conn.find("./views/breadboardView/p")
        if bb_p is None:
            continue

        sid = bb_p.get("svgId")
        tid = bb_p.get("terminalId")

        center_vb = None
        if tid and tid in id_map:
            el_t, mat_t = id_map[tid]
            center_vb = _resolve_element_center(el_t, mat_t)
        if center_vb is None and sid and sid in id_map:
            el_s, mat_s = id_map[sid]
            center_vb = _resolve_element_center(el_s, mat_s)
        if center_vb is None:
            continue

        vb_connectors.append((cid, cname, _classify_pin_type(cname, ctype), cdesc, center_vb[0], center_vb[1]))

    if not vb_connectors or len(vb_connectors) > 256:
        return None, None, None, f"Unsupported pin count ({len(vb_connectors)})"

    dpi_candidates = (96.0,) if explicit_units else (96.0, 72.0, 90.0)
    best_result = None

    for dpi in dpi_candidates:
        scale_factor = 1.0 if explicit_units else (96.0 / dpi)
        sx_mm = base_sx_mm * scale_factor
        sy_mm = base_sy_mm * scale_factor
        w_mm = base_w_mm * scale_factor
        h_mm = base_h_mm * scale_factor
        if not (0.05 <= w_mm <= 1000.0 and 0.05 <= h_mm <= 1000.0):
            continue

        raw_conns = [
            (cid, cname, ptype, cdesc, (cx - vb_x) * sx_mm, (cy - vb_y) * sy_mm)
            for (cid, cname, ptype, cdesc, cx, cy) in vb_connectors
        ]
        score, aligned, unbused = _evaluate_alignment(raw_conns, bus_adj)
        full_score = (score[0], score[1], 1 if dpi == 96.0 else 0)
        if best_result is None or full_score > best_result[0]:
            best_result = (full_score, aligned, raw_conns, w_mm, h_mm, unbused)

    if best_result is None:
        raw_conns = [
            (cid, cname, ptype, cdesc, (cx - vb_x) * base_sx_mm, (cy - vb_y) * base_sy_mm)
            for (cid, cname, ptype, cdesc, cx, cy) in vb_connectors
        ]
        score, aligned, unbused = _evaluate_alignment(raw_conns, bus_adj)
        best_result = ((score[0], score[1], 1), aligned, raw_conns, base_w_mm, base_h_mm, unbused)

    _, best_aligned, raw_connectors, svg_w_mm, svg_h_mm, best_unbused = best_result
    orig_comp = _build_fritzing_component_def(
        entry, fzp_root, svg_bytes, raw_connectors, svg_w_mm, svg_h_mm, best_aligned, bus_adj
    )

    scaled_comp: FritzingComponentDef | None = None
    best_scale: float | None = None
    if len(orig_comp.off_grid_pins) > 0:
        orig_aligned_cnt = len(orig_comp.pins)
        orig_unbused_cnt = len(best_unbused)
        scaled_match = _find_best_scaled_alignment(
            raw_connectors, svg_w_mm, svg_h_mm, bus_adj, orig_aligned_cnt, orig_unbused_cnt
        )
        if scaled_match is not None:
            best_scale, s_conns, s_w, s_h, s_aligned = scaled_match
            scaled_comp = _build_fritzing_component_def(
                entry, fzp_root, svg_bytes, s_conns, s_w, s_h, s_aligned, bus_adj, scale_factor=best_scale
            )

    return orig_comp, scaled_comp, best_scale, None


def parse_and_validate_fritzing_part(
    entry: FritzingCatalogEntry,
    fzp_bytes: bytes,
    svg_bytes: bytes,
) -> tuple[FritzingComponentDef | None, str | None]:
    """
    Validates PerfBoard compatibility for a Fritzing part (including unaligned jumper-only parts).
    Returns (FritzingComponentDef, None) if valid, else (None, reason).
    """
    orig_comp, _scaled, _scale, reason = parse_fritzing_part_options(entry, fzp_bytes, svg_bytes)
    return orig_comp, reason


def _read_local_fzp_with_svg(fzp_path: str) -> tuple[bytes, bytes]:
    """Reads a loose .fzp and locates its breadboard SVG next to it or in a fritzing-parts tree."""
    with open(fzp_path, "rb") as f:
        fzp_bytes = f.read()
    fzp_root = ET.fromstring(fzp_bytes)
    bb_layers = fzp_root.find("./views/breadboardView/layers")
    if bb_layers is None or not bb_layers.get("image"):
        raise ValueError("Part has no breadboard view")

    raw_img = bb_layers.get("image", "").replace("\\", "/").lstrip("/")
    if not raw_img or ".." in raw_img.split("/"):
        raise ValueError(f"Unsafe breadboard SVG path: {bb_layers.get('image', '')}")

    base_dir = os.path.dirname(os.path.abspath(fzp_path))
    candidates = [
        os.path.join(base_dir, raw_img),
        os.path.join(base_dir, os.path.basename(raw_img)),
    ]
    # Support both <root>/{core,pdb}/x.fzp and <root>/pdb/{core,contrib,user,obsolete}/x.fzp
    parent = os.path.dirname(base_dir)
    grandparent = os.path.dirname(parent)
    for root_dir in (parent, grandparent):
        if not root_dir:
            continue
        for sub in ("core", "contrib", "user", "obsolete"):
            candidates.append(os.path.join(root_dir, "svg", sub, raw_img))
        candidates.append(os.path.join(root_dir, "svg", raw_img))

    for cand in candidates:
        if os.path.isfile(cand):
            if os.path.getsize(cand) > _MAX_LOCAL_FILE_BYTES:
                raise ValueError("Breadboard SVG file is too large")
            with open(cand, "rb") as f:
                return fzp_bytes, f.read()
    raise ValueError(f"Breadboard SVG '{raw_img}' not found next to the .fzp file")


def import_fritzing_file_with_options(
    path: str,
) -> tuple[FritzingComponentDef | None, FritzingComponentDef | None, float | None, str | None]:
    """
    Imports a local .fzpz archive or .fzp + breadboard SVG, returning:
    (orig_comp, scaled_comp, scale_factor, error_reason).
    If a uniform scale factor aligns unaligned pins to 2.54 mm, scaled_comp is populated.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".fzpz", ".fzp"):
        return None, None, None, "Unsupported file type (expected .fzpz or .fzp)"
    try:
        if os.path.getsize(path) > _MAX_LOCAL_FILE_BYTES:
            return None, None, None, "File is too large"
        if ext == ".fzpz":
            with open(path, "rb") as f:
                fzp_bytes, svg_bytes = _read_fzpz_bytes(f.read())
        else:
            fzp_bytes, svg_bytes = _read_local_fzp_with_svg(path)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        return None, None, None, str(exc)

    stem = re.sub(r"[^a-zA-Z0-9]+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_").lower()[:36] or "part"
    digest = hashlib.sha1(fzp_bytes + svg_bytes).hexdigest()[:8]
    entry = FritzingCatalogEntry(
        source_name="Local",
        repo="",
        branch="",
        kind="fzpz" if ext == ".fzpz" else "local_fzp",
        path=os.path.abspath(path),
        display_name=_clean_display_name(path),
        type_id=f"fritzing_{stem}_{digest}",
    )
    return parse_fritzing_part_options(entry, fzp_bytes, svg_bytes)


def import_fritzing_file(path: str) -> tuple[FritzingComponentDef | None, str | None]:
    """
    Imports a local .fzpz archive, or a .fzp with its breadboard SVG alongside it.
    Returns (component, None) if valid, else (None, reason).
    """
    orig_comp, _scaled, _scale, reason = import_fritzing_file_with_options(path)
    return orig_comp, reason


def search_compatible_fritzing_parts(
    query: str,
    exclude_type_ids: set[str] | None = None,
    cancel_event: threading.Event | None = None,
    on_compatible_cb: Callable[[FritzingComponentDef], None] | None = None,
    limit_candidates: int = 24,
) -> list[FritzingComponentDef]:
    """
    Searches public Fritzing catalogs, validates candidate compatibility concurrently,
    and invokes on_compatible_cb for each compatible 2.54 mm component found.
    """
    candidates = search_catalog_candidates(
        query,
        exclude_type_ids=exclude_type_ids,
        limit=limit_candidates,
    )
    forum_candidates = search_fritzing_forum_candidates(
        query,
        exclude_type_ids=exclude_type_ids,
        cancel_event=cancel_event,
        limit=8,
    )
    seen_ids = {c.type_id for c in candidates}
    for fc in forum_candidates:
        if fc.type_id not in seen_ids:
            candidates.append(fc)
            seen_ids.add(fc.type_id)
    if not candidates or (cancel_event is not None and cancel_event.is_set()):
        return []

    compatible: list[FritzingComponentDef] = []

    def _check_one(entry: FritzingCatalogEntry) -> FritzingComponentDef | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            fzp_bytes, svg_bytes = _download_candidate_files(entry)
            if cancel_event is not None and cancel_event.is_set():
                return None
            comp_def, _reason = parse_and_validate_fritzing_part(entry, fzp_bytes, svg_bytes)
            return comp_def
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, zipfile.BadZipFile):
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_check_one, c) for c in candidates]
        for fut in as_completed(futs):
            if cancel_event is not None and cancel_event.is_set():
                break
            comp_def = fut.result()
            if comp_def is not None:
                compatible.append(comp_def)
                if on_compatible_cb is not None:
                    on_compatible_cb(comp_def)

    return compatible
