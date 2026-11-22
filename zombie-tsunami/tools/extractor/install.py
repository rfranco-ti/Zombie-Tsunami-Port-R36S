"""Instala o payload do Zombie Tsunami a partir do APK, com validação e staging.

Mesmo contrato do kit do Punch Quest: protocolo de texto por linha na stdout,
manifesto com hashes, staging atômico e marker por último. O backend não toca
nas bibliotecas do FMOD nem em save/logs.
"""

import fcntl
import hashlib
import io
import json
import os
import shutil
import signal
import struct
import sys
import tempfile
import time
import zipfile

MANIFEST_NAME = "payload-manifest.json"
MARKER_NAME = "installed.json"
LOCK_NAME = ".install.lock"
STAGE_PREFIX = ".install_tmp-"
OLD_ASSETS = ".assets.old"
LIB_ENTRY_ROOT = "lib/arm64-v8a/"
ASSET_ENTRY_ROOT = "assets/res/"
ASSET_OUTPUT_ROOT = ("assets", "res")
PAYLOAD_DIR = "payload"
GAMEDATA_DIR = "gamedata"
ARCHIVE_EXTENSIONS = (".apk", ".apkm", ".xapk")
BUNDLE_EXTENSIONS = (".apkm", ".xapk")
BASE_APK_NAME = "base.apk"
DISK_MARGIN_BYTES = 96 * 1024 * 1024


def emit(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def emit_stage(text):
    emit("STAGE " + text)


def emit_progress(value, current, total, name):
    emit("PROGRESS %d %d %d %s" % (value, current, total, name))


def emit_log(level, text):
    emit("LOG %s %s" % (level, text))


def emit_error(text):
    emit("ERROR " + text)


def emit_complete():
    emit("COMPLETE")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(entries):
    digest = hashlib.sha256()
    for relative, size, file_hash in sorted(entries, key=lambda item: item[0]):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def payload_path(game_dir, *parts):
    return os.path.join(game_dir, PAYLOAD_DIR, *parts)


def assets_root(game_dir):
    return payload_path(game_dir, "assets")


def assets_path(game_dir):
    return payload_path(game_dir, *ASSET_OUTPUT_ROOT)


def old_assets_path(game_dir):
    return os.path.join(assets_root(game_dir), OLD_ASSETS)


def load_manifest(game_dir):
    path = os.path.join(game_dir, "tools", "extractor", MANIFEST_NAME)
    if not os.path.isfile(path):
        raise FileNotFoundError("manifesto ausente: " + path)
    with open(path, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema") != 1:
        raise ValueError("schema de manifesto não suportado")
    return manifest


def marker_path(game_dir):
    return os.path.join(game_dir, GAMEDATA_DIR, MARKER_NAME)


def read_marker(game_dir):
    path = marker_path(game_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


def marker_is_valid(game_dir, manifest):
    marker = read_marker(game_dir)
    if not marker or marker.get("version") != manifest["version"]:
        return False
    if marker.get("apk_sha256") != manifest["apk"]["sha256"]:
        return False
    assets = assets_path(game_dir)
    if not os.path.isdir(assets):
        return False
    for anchor in manifest["assets"].get("anchors", []):
        if not os.path.exists(os.path.join(assets, *anchor.split("/"))):
            return False
    libraries = marker.get("libraries", {})
    for entry in manifest["libraries"]:
        installed = libraries.get(entry["name"])
        if not installed:
            return False
        path = payload_path(game_dir, entry["name"])
        if not os.path.isfile(path) or os.path.getsize(path) != installed.get("size"):
            return False
    return True


def find_apks(game_dir):
    root = os.path.join(game_dir, GAMEDATA_DIR)
    found = []
    if not os.path.isdir(root):
        return found
    for current, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories if not name.startswith(STAGE_PREFIX)
        )
        for name in sorted(files):
            if name.lower().endswith(ARCHIVE_EXTENSIONS):
                found.append(os.path.join(current, name))
    return found


def read_string_pool(data, offset, header_size):
    count, = struct.unpack_from("<I", data, offset + 8)
    flags, = struct.unpack_from("<I", data, offset + 16)
    strings_start, = struct.unpack_from("<I", data, offset + 20)
    base = offset + strings_start
    utf8 = bool(flags & 0x100)
    strings = []
    for index in range(count):
        relative, = struct.unpack_from("<I", data, offset + header_size + index * 4)
        cursor = base + relative
        if utf8:
            length = data[cursor]
            cursor += 1
            if length & 0x80:
                length = ((length & 0x7F) << 8) | data[cursor]
                cursor += 1
            strings.append(data[cursor:cursor + length].decode("utf-8", "replace"))
        else:
            length, = struct.unpack_from("<H", data, cursor)
            cursor += 2
            strings.append(data[cursor:cursor + length * 2].decode("utf-16le", "replace"))
    return strings


def parse_android_manifest_unchecked(data):
    if len(data) < 8 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        return None
    strings = None
    offset = 8
    while offset + 8 <= len(data):
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        if chunk_size < 8:
            return None
        if chunk_type == 0x0001:
            strings = read_string_pool(data, offset, header_size)
        elif chunk_type == 0x0102 and strings is not None:
            extension = offset + header_size
            name_index, = struct.unpack_from("<I", data, extension + 4)
            if name_index < len(strings) and strings[name_index] == "manifest":
                attribute_start, attribute_size, attribute_count = struct.unpack_from(
                    "<HHH", data, extension + 8
                )
                result = {}
                for index in range(attribute_count):
                    attribute = extension + attribute_start + index * attribute_size
                    attribute_name, raw_value = struct.unpack_from("<II", data, attribute + 4)
                    value_type = data[attribute + 15]
                    typed_value, = struct.unpack_from("<I", data, attribute + 16)
                    if attribute_name >= len(strings):
                        continue
                    name = strings[attribute_name]
                    if value_type == 0x03 and raw_value != 0xFFFFFFFF:
                        value = strings[raw_value]
                    elif value_type in (0x10, 0x11):
                        value = typed_value
                    else:
                        continue
                    if name == "package" and isinstance(value, str):
                        result["package"] = value
                    elif name == "versionName" and isinstance(value, str):
                        result["version_name"] = value
                    elif name == "versionCode" and isinstance(value, int):
                        result["version_code"] = value
                return result or None
        elif chunk_type == 0x0103:
            return None
        offset += chunk_size
    return None


def parse_android_manifest(data):
    try:
        return parse_android_manifest_unchecked(data)
    except (struct.error, IndexError, UnicodeDecodeError):
        return None


def read_manifest_info(archive):
    try:
        data = archive.read("AndroidManifest.xml")
    except KeyError:
        return None
    return parse_android_manifest(data)


def manifest_info_from_bytes(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            return read_manifest_info(archive)
    except zipfile.BadZipFile:
        return None


def select_base_member(members):
    for member in members:
        if member.filename.lower().rsplit("/", 1)[-1] == BASE_APK_NAME:
            return member
    return max(members, key=lambda member: member.file_size)


def inspect_bundle(bundle):
    members = [
        item
        for item in bundle.infolist()
        if item.filename.lower().endswith(".apk") and not item.filename.endswith("/")
    ]
    if not members:
        raise ValueError("Pacote inválido: base.apk não encontrado")
    member = select_base_member(members)
    data = bundle.read(member)
    return {
        "sha256": sha256_bytes(data),
        "size": len(data),
        "info": manifest_info_from_bytes(data),
        "data": data,
        "entry": member.filename,
    }


def inspect_apk(path):
    name = os.path.basename(path)
    if path.lower().endswith(BUNDLE_EXTENSIONS):
        try:
            with zipfile.ZipFile(path, "r") as bundle:
                return inspect_bundle(bundle)
        except zipfile.BadZipFile:
            raise ValueError("Arquivo %s não é um APK, APKM ou XAPK válido" % name)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            info = read_manifest_info(archive)
            if info is None:
                return inspect_bundle(archive)
            return {
                "sha256": sha256_file(path),
                "size": os.path.getsize(path),
                "info": info,
                "data": None,
                "entry": None,
            }
    except zipfile.BadZipFile:
        raise ValueError("Arquivo %s não é um APK, APKM ou XAPK válido" % name)


def incompatibility_message(candidate, manifest):
    expected = manifest["apk"]
    info = candidate.get("info") or {}
    expected_version = expected.get("version", "")
    expected_package = expected.get("package", "")
    found_package = info.get("package")
    found_version = info.get("version_name")
    if found_package and found_package != expected_package:
        return "Este arquivo não é o Zombie Tsunami %s" % expected_version
    if found_version and found_version != expected_version:
        return "Versão %s não é compatível; use %s" % (found_version, expected_version)
    if found_version == expected_version:
        return "SHA-256 não confere; baixe o Zombie Tsunami %s novamente" % expected_version
    return "Arquivo não reconhecido; use o Zombie Tsunami %s" % expected_version


def verify_candidate(candidate, manifest):
    expected = manifest["apk"]
    if candidate["size"] == expected["size"] and candidate["sha256"] == expected["sha256"]:
        return candidate["sha256"], None
    return candidate["sha256"], incompatibility_message(candidate, manifest)


def safe_member(name, prefix):
    if not name.startswith(prefix):
        raise ValueError("entrada fora do prefixo esperado: " + name)
    relative = name[len(prefix):]
    if not relative or relative.endswith("/"):
        return None
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts) or relative.startswith("/"):
        raise ValueError("entrada com caminho inseguro: " + name)
    return relative


def check_free_space(game_dir, manifest):
    needed = int(manifest["assets"]["size"])
    for entry in manifest["libraries"]:
        needed += int(entry["size"])
    needed += DISK_MARGIN_BYTES
    usage = shutil.disk_usage(game_dir)
    if usage.free < needed:
        raise ValueError(
            "espaço insuficiente: %d MB livres, %d MB necessários"
            % (usage.free // (1024 * 1024), needed // (1024 * 1024))
        )


def recover_commit(game_dir):
    assets = assets_path(game_dir)
    old_assets = old_assets_path(game_dir)
    if not os.path.isdir(old_assets):
        return
    if os.path.isdir(assets):
        shutil.rmtree(old_assets)
        return
    os.replace(old_assets, assets)


def clear_stale_staging(game_dir):
    for name in os.listdir(game_dir):
        if name.startswith(STAGE_PREFIX):
            shutil.rmtree(os.path.join(game_dir, name), ignore_errors=True)


def acquire_lock(game_dir):
    path = os.path.join(game_dir, GAMEDATA_DIR, LOCK_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("outra instalação está em andamento")
    return handle


def release_lock(handle):
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def extract_assets(archive, stage, manifest):
    root = os.path.join(stage, *ASSET_OUTPUT_ROOT)
    os.makedirs(root, exist_ok=True)
    expected = manifest["assets"]
    entries = []
    total_bytes = 0
    members = [
        item
        for item in archive.infolist()
        if item.filename.startswith(ASSET_ENTRY_ROOT) and not item.filename.endswith("/")
    ]
    if len(members) != expected["count"]:
        raise ValueError(
            "APK traz %d assets; o manifesto espera %d"
            % (len(members), expected["count"])
        )
    for index, member in enumerate(members):
        relative = safe_member(member.filename, ASSET_ENTRY_ROOT)
        if relative is None:
            continue
        target = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with archive.open(member, "r") as source, open(target, "wb") as target_stream:
            while True:
                block = source.read(262144)
                if not block:
                    break
                target_stream.write(block)
                digest.update(block)
                written += len(block)
        entries.append((relative, written, digest.hexdigest()))
        total_bytes += written
        if index == 0 or (index + 1) % 20 == 0 or index + 1 == len(members):
            emit_progress(
                10 + int((index + 1) / max(len(members), 1) * 48),
                index + 1,
                len(members),
                relative,
            )
    if len(entries) != expected["count"] or total_bytes != expected["size"]:
        raise ValueError(
            "assets extraídos: %d arquivos, %d bytes; esperado %d, %d"
            % (len(entries), total_bytes, expected["count"], expected["size"])
        )
    digest = tree_digest(entries)
    if digest != expected["tree_sha256"]:
        raise ValueError("digest dos assets não confere")
    emit_log("OK", "assets verificados: %d arquivos, %d bytes" % (len(entries), total_bytes))
    return digest


def extract_libraries(archive, stage, manifest):
    root = os.path.join(stage, "libs")
    os.makedirs(root, exist_ok=True)
    libraries = manifest["libraries"]
    for index, entry in enumerate(libraries):
        name = entry["name"]
        member_name = LIB_ENTRY_ROOT + name
        try:
            member = archive.getinfo(member_name)
        except KeyError:
            raise ValueError("biblioteca ausente no APK: " + name)
        data = archive.read(member)
        if sha256_bytes(data) != entry["sha256"]:
            raise ValueError("hash de origem não confere: " + name)
        with open(os.path.join(root, name), "wb") as stream:
            stream.write(data)
        emit_progress(
            60 + int((index + 1) / max(len(libraries), 1) * 20),
            index + 1,
            len(libraries),
            name,
        )
    emit_log("OK", "%d bibliotecas verificadas" % len(libraries))


def commit(stage, game_dir, manifest, apk_sha):
    recover_commit(game_dir)
    os.makedirs(assets_root(game_dir), exist_ok=True)
    assets = assets_path(game_dir)
    old_assets = old_assets_path(game_dir)
    staged_assets = os.path.join(stage, *ASSET_OUTPUT_ROOT)
    if os.path.isdir(assets):
        os.replace(assets, old_assets)
    os.replace(staged_assets, assets)
    if os.path.isdir(old_assets):
        shutil.rmtree(old_assets)

    payload = payload_path(game_dir)
    os.makedirs(payload, exist_ok=True)
    installed = {}
    for entry in manifest["libraries"]:
        name = entry["name"]
        source = os.path.join(stage, "libs", name)
        target = os.path.join(payload, name)
        os.replace(source, target)
        installed[name] = {"size": os.path.getsize(target), "sha256": entry["sha256"]}

    marker = {
        "schema": 1,
        "version": manifest["version"],
        "apk_sha256": apk_sha,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "assets": {
            "count": manifest["assets"]["count"],
            "size": manifest["assets"]["size"],
            "tree_sha256": manifest["assets"]["tree_sha256"],
        },
        "libraries": installed,
    }
    temporary = marker_path(game_dir) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(marker, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, marker_path(game_dir))
    os.sync()


def install(apk_path, candidate, game_dir, manifest, apk_sha, delete_apk):
    check_free_space(game_dir, manifest)
    stage = tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=game_dir)
    try:
        emit_stage("Extraindo assets")
        if candidate["data"] is not None:
            archive_source = zipfile.ZipFile(io.BytesIO(candidate["data"]), "r")
        else:
            archive_source = zipfile.ZipFile(apk_path, "r")
        with archive_source as archive:
            if archive.testzip() is not None:
                raise ValueError("APK corrompido")
            extract_assets(archive, stage, manifest)
            emit_stage("Instalando bibliotecas")
            extract_libraries(archive, stage, manifest)
        emit_stage("Instalando arquivos")
        emit_progress(88, 0, 0, "Commit")
        commit(stage, game_dir, manifest, apk_sha)
        if delete_apk:
            os.unlink(apk_path)
            emit_log("INFO", "pacote removido após a instalação")
        emit_progress(100, 0, 0, "Concluido")
        emit_log("OK", "instalação concluída")
        emit_complete()
        return 0
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def report_check(game_dir, manifest, force):
    if not force and marker_is_valid(game_dir, manifest):
        emit("INSTALLED " + manifest["version"])
        return 0
    apks = find_apks(game_dir)
    if not apks:
        emit("APK_MISSING")
        return 1
    if len(apks) > 1:
        emit("APK_AMBIGUOUS %d" % len(apks))
        return 1
    try:
        candidate = inspect_apk(apks[0])
    except ValueError as error:
        emit("APK_INVALID " + str(error))
        return 1
    actual, problem = verify_candidate(candidate, manifest)
    if problem:
        emit("APK_MISMATCH %s %s" % (actual, problem))
        return 1
    emit("APK_FOUND " + apks[0])
    return 0


def main(argv):
    mode = None
    force = False
    delete_apk = False
    positional = []
    for argument in argv:
        if argument == "--check":
            mode = "check"
        elif argument == "--progress":
            mode = "progress"
        elif argument == "--force":
            force = True
        elif argument == "--delete-apk":
            delete_apk = True
        elif argument.startswith("-"):
            emit_error("argumento desconhecido: " + argument)
            return 2
        else:
            positional.append(argument)
    if mode is None:
        emit_error("use --check ou --progress")
        return 2
    game_dir = os.path.abspath(positional[0] if positional else ".")
    try:
        manifest = load_manifest(game_dir)
    except (OSError, ValueError) as error:
        emit_error(str(error))
        return 1
    recover_commit(game_dir)
    if mode == "check":
        try:
            return report_check(game_dir, manifest, force)
        except (OSError, ValueError) as error:
            emit_error(str(error))
            return 1
    if not force and marker_is_valid(game_dir, manifest):
        emit_log("INFO", "dados do jogo já instalados")
        emit_complete()
        return 0
    try:
        lock = acquire_lock(game_dir)
    except (OSError, RuntimeError) as error:
        emit_error(str(error))
        return 1
    try:
        clear_stale_staging(game_dir)
        emit_stage("Verificando APK")
        emit_progress(2, 0, 0, "Procurando APK")
        apks = find_apks(game_dir)
        if not apks:
            emit_error("APK não encontrado em gamedata/")
            return 1
        if len(apks) > 1:
            emit_error("mais de um APK, APKM ou XAPK em gamedata/; deixe apenas um")
            return 1
        apk_path = apks[0]
        emit_log("INFO", "APK encontrado: " + os.path.relpath(apk_path, game_dir))
        candidate = inspect_apk(apk_path)
        apk_sha, problem = verify_candidate(candidate, manifest)
        if problem:
            emit_error(problem)
            return 1
        emit_log("OK", "SHA-256 do APK confere")
        return install(apk_path, candidate, game_dir, manifest, apk_sha, delete_apk)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        emit_error(str(error))
        return 1
    finally:
        release_lock(lock)
        os.sync()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(130))
    signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(130))
    sys.exit(main(sys.argv[1:]))
