from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence, TYPE_CHECKING

import logging
import pandas as pd

if TYPE_CHECKING:
    from app.config import AppPaths

__all__ = [
    "BlacklistKind",
    "DataSource",
    "DataCatalog",
    "load_catalog",
    "reload_catalog",
    "clean_value",
    "detect_blacklist_kind",
]

logger = logging.getLogger(__name__)

BlacklistKind = Literal["critical", "elevated", "unknown"]


@dataclass(frozen=True)
class DataSource:
    """Описывает один Excel-файл, загруженный в память.

    - path: полный путь к файлу
    - name: имя файла (без директорий)
    - mtime: время последней модификации (float, как из stat().st_mtime)
    - df: исходный DataFrame (как прочитан из Excel, header=None)
    - df_norm: нормализованный DataFrame (все ячейки приведены к str через clean_value)
    - blacklist_kind: None для carriers/forwarders; для blacklist — 'critical' | 'elevated' | 'unknown'
    """

    path: Path
    name: str
    mtime: float
    df: pd.DataFrame
    df_norm: pd.DataFrame
    blacklist_kind: BlacklistKind | None = None


@dataclass(frozen=True)
class DataCatalog:
    """Каталог всех источников.

    - carriers: список источников перевозчиков
    - forwarders: список источников экспедиторов
    - blacklist: список источников ЧС (у каждого blacklist_kind заполнен)
    """

    carriers: list[DataSource]
    forwarders: list[DataSource]
    blacklist: list[DataSource]


def clean_value(x: object) -> str:
    """Приводит ячейку Excel к строке для строгого сравнения.

    - None / NaN -> ""
    - Числа (int/float) -> str(int(x)) если возможно (чтобы 1024.0 -> "1024"); иначе str(x)
    - Прочее -> str(x).strip()
    """

    if x is None:
        return ""
    if isinstance(x, bool):
        return "True" if x else "False"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        if pd.isna(x):
            return ""
        if x.is_integer():
            return str(int(x))
        return str(x)
    if not isinstance(x, str) and hasattr(x, "__float__"):
        try:
            float_value = float(x)
        except (TypeError, ValueError):
            pass
        else:
            if pd.isna(float_value):
                return ""
            is_integer = False
            is_integer_attr = getattr(x, "is_integer", None)
            if callable(is_integer_attr):
                try:
                    is_integer = bool(is_integer_attr())
                except (TypeError, ValueError):
                    is_integer = float_value.is_integer()
            else:
                is_integer = float_value.is_integer()
            if is_integer:
                return str(int(float_value))
            return str(float_value)
    try:
        if pd.isna(x):
            return ""
    except (TypeError, ValueError):
        pass
    return str(x).strip()


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Возвращает копию df, где ко всем ячейкам применён clean_value.

    Пустые значения превращаются в "".
    """

    return df.applymap(clean_value)


def _scan_dir(dir_path: Path) -> list[Path]:
    """Возвращает список путей к *.xlsx в dir_path (без рекурсии).

    Если директории нет — возвращает пустой список. Результат отсортирован
    по имени файла без учёта регистра.
    """

    if not dir_path.exists() or not dir_path.is_dir():
        return []
    paths = [path for path in dir_path.iterdir() if path.is_file() and path.suffix.lower() == ".xlsx"]
    return sorted(paths, key=lambda p: p.name.casefold())


def _read_excel_file(path: Path) -> pd.DataFrame:
    """Читает первый лист Excel (header=None, engine='openpyxl')."""

    return pd.read_excel(path, engine="openpyxl", header=None, dtype=object)


def detect_blacklist_kind(filename: str) -> BlacklistKind:
    """Классифицирует файл чёрного списка по имени (регистронезависимо).

    - если содержит 'негатив' -> 'critical'
    - elif содержит 'настораж' -> 'elevated'
    - else -> 'unknown'
    """

    lowered = filename.casefold()
    if "негатив" in lowered:
        return "critical"
    if "настораж" in lowered:
        return "elevated"
    return "unknown"


def _build_sources(file_paths: Sequence[Path], *, kind: str | None) -> list[DataSource]:
    """Универсальная сборка DataSource из списка путей.

    kind=None используется для перевозчиков и экспедиторов. Для kind='blacklist'
    дополнительно заполняется blacklist_kind на основе имени файла. Ошибки
    чтения логируются и приводят к пропуску файла.
    """

    sources: list[DataSource] = []
    for path in file_paths:
        try:
            df = _read_excel_file(path)
            df_norm = _normalize_df(df)
            mtime = path.stat().st_mtime
            blacklist_kind: BlacklistKind | None
            if kind == "blacklist":
                blacklist_kind = detect_blacklist_kind(path.name)
            else:
                blacklist_kind = None
            sources.append(
                DataSource(
                    path=path,
                    name=path.name,
                    mtime=mtime,
                    df=df,
                    df_norm=df_norm,
                    blacklist_kind=blacklist_kind,
                )
            )
        except Exception:
            logger.warning("Skip broken file: %s", path)
    sources.sort(key=lambda src: src.name.casefold())
    return sources


def _load_section(paths: "AppPaths", attr: str, *, kind: str | None) -> list[DataSource]:
    """Загружает раздел каталога по имени атрибута в AppPaths."""

    dir_path = getattr(paths, attr)
    file_paths = _scan_dir(dir_path)
    return _build_sources(file_paths, kind=kind)


def load_catalog(paths: "AppPaths") -> DataCatalog:
    """Полная загрузка каталога из трёх директорий.

    Читает .xlsx файлы из paths.excel_carriers_dir, paths.excel_forwarders_dir и
    paths.excel_blacklist_dir. Для каждого файла считывается первый лист
    (header=None, engine='openpyxl') и подготавливаются как исходный DataFrame,
    так и нормализованная копия для быстрых поисков.
    """

    carriers = _load_section(paths, "excel_carriers_dir", kind=None)
    forwarders = _load_section(paths, "excel_forwarders_dir", kind=None)
    blacklist = _load_section(paths, "excel_blacklist_dir", kind="blacklist")
    return DataCatalog(carriers=carriers, forwarders=forwarders, blacklist=blacklist)


def reload_catalog(paths: "AppPaths", prev: DataCatalog | None = None) -> DataCatalog:
    """«Горячая» перезагрузка с переиспользованием неизменённых файлов.

    Если prev не передан — работает как load_catalog. Для каждого раздела
    сравнивает текущее состояние директорий с предыдущим по пути и времени
    модификации, перечитывая только новые или изменённые файлы.
    """

    if prev is None:
        return load_catalog(paths)

    carriers = _reload_section(paths, prev.carriers, "excel_carriers_dir", kind=None)
    forwarders = _reload_section(paths, prev.forwarders, "excel_forwarders_dir", kind=None)
    blacklist = _reload_section(paths, prev.blacklist, "excel_blacklist_dir", kind="blacklist")
    return DataCatalog(carriers=carriers, forwarders=forwarders, blacklist=blacklist)


def _reload_section(
    paths: "AppPaths",
    previous: Iterable[DataSource],
    attr: str,
    *,
    kind: str | None,
) -> list[DataSource]:
    """Переиспользует ранее загруженные источники для одной директории."""

    dir_path = getattr(paths, attr)
    file_paths = _scan_dir(dir_path)
    prev_by_path = {source.path: source for source in previous}

    reused: list[DataSource] = []
    to_reload: list[Path] = []

    for path in file_paths:
        prev_source = prev_by_path.get(path)
        if prev_source is None:
            to_reload.append(path)
            continue
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            logger.warning("Skip broken file: %s", path)
            continue
        if prev_source.mtime == current_mtime:
            reused.append(prev_source)
        else:
            to_reload.append(path)

    reloaded = _build_sources(to_reload, kind=kind)
    combined = reused + reloaded
    combined.sort(key=lambda src: src.name.casefold())
    return combined
