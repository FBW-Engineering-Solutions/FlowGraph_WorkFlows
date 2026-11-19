#!/usr/bin/env python3
"""Dependency-free static catalog validation. Never imports or executes workflow code."""

import argparse
from collections import deque
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z", re.IGNORECASE)


class InvalidCatalog(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidCatalog(message)


def text(value, label, limit=200, empty=False):
    require(isinstance(value, str), f"{label} must be text")
    require((empty or bool(value.strip())) and len(value) <= limit,
            f"{label} must be {'0' if empty else '1'}–{limit} characters")
    require(not any(ord(c) < 32 and c not in '\t\n\r' or ord(c) == 127 for c in value),
            f"{label} contains control characters")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise InvalidCatalog(f"non-finite JSON number: {value}")


def read_json(path):
    require(not path.is_symlink(), f"symlink is not allowed: {path}")
    require(path.is_file(), f"missing file: {path}")
    require(path.stat().st_size <= MAX_BYTES, f"file exceeds 2 MiB: {path}")
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidCatalog(f"invalid UTF-8 JSON in {path}: {exc}") from exc


def object_value(value, label):
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def array(value, label):
    require(isinstance(value, list), f"{label} must be an array")
    return value


def validate_workflow(workflow, label='workflow', depth=0):
    require(depth <= 32, f"{label}: nested workflows exceed depth 32")
    object_value(workflow, label)
    require(workflow.get('format') == 'flowgraph-workflow', f"{label}: wrong format")
    require(type(workflow.get('version')) is int and workflow['version'] in (1, 2, 3),
            f"{label}: supported workflow format versions are 1, 2, 3")
    nodes = {}
    for node in array(workflow.get('nodes'), f'{label}.nodes'):
        object_value(node, f'{label}.node')
        node_id = text(node.get('id'), 'node.id', 500)
        require(node_id not in nodes, f"{label}: duplicate node ID {node_id}")
        nodes[node_id] = node
        definition = text(node.get('definition_id'), 'node.definition_id', 200)
        parameters = object_value(node.get('parameters'), 'node.parameters')
        if 'position' in node:
            position = object_value(node['position'], 'node.position')
            for axis in ('x', 'y'):
                coordinate = position.get(axis)
                require(type(coordinate) in (int, float) and math.isfinite(coordinate),
                        f'{label}: position.{axis} must be finite')
        if definition == 'user-function':
            code = parameters.get('code')
            require(isinstance(code, str) or (isinstance(code, list) and bool(code)
                    and all(isinstance(line, str) and '\n' not in line and '\r' not in line
                            for line in code)), f'{label}: invalid user-function code representation')
        require(not ('subworkflow' in node and 'subworkflows' in node),
                f'{label}: conflicting nested workflow representations')
        if 'subworkflow' in node:
            require(workflow['version'] < 3, f'{label}: version 3 requires subworkflows')
            validate_workflow(node['subworkflow'], f'{label}/{node_id}/default', depth + 1)
        if 'subworkflows' in node:
            children = object_value(node['subworkflows'], 'node.subworkflows')
            for key, child in children.items():
                text(key, 'subworkflow key', 200)
                validate_workflow(child, f'{label}/{node_id}/{key}', depth + 1)
            if definition == 'conditional-workflow':
                require(set(children) == {'true', 'false'},
                        f'{label}: conditional workflow needs true and false children')
            if definition in ('run-workflow', 'batch-workflow'):
                require(set(children) == {'default'}, f'{label}: composite needs default child')

    adjacency = {node_id: set() for node_id in nodes}
    incoming = {node_id: 0 for node_id in nodes}
    targets = set()
    for edge in array(workflow.get('edges'), f'{label}.edges'):
        object_value(edge, 'edge')
        for side in ('source', 'target'):
            node_id = text(edge.get(f'{side}_node'), f'edge.{side}_node', 500)
            require(node_id in nodes, f'{label}: dangling {side} node {node_id}')
            text(edge.get(f'{side}_port'), f'edge.{side}_port', 500)
        target = (edge['target_node'], edge['target_port'])
        require(target not in targets, f'{label}: multiple edges target the same input {target}')
        targets.add(target)
        source, destination = edge['source_node'], edge['target_node']
        if destination not in adjacency[source]:
            adjacency[source].add(destination)
            incoming[destination] += 1

    ready = deque(node for node, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        visited += 1
        for destination in adjacency[ready.popleft()]:
            incoming[destination] -= 1
            if incoming[destination] == 0:
                ready.append(destination)
    require(visited == len(nodes), f'{label}: workflow contains a cycle')

    for direction in ('inputs', 'outputs'):
        names = set()
        for port in array(workflow.get(direction, []), f'{label}.{direction}'):
            object_value(port, f'{direction} port')
            name = text(port.get('name'), f'{direction}.name', 500)
            require(name not in names, f'{label}: duplicate {direction} name {name}')
            names.add(name)
            node_id = text(port.get('node_id'), f'{direction}.node_id', 500)
            require(node_id in nodes, f'{label}: dangling {direction} node {node_id}')
            text(port.get('node_port'), f'{direction}.node_port', 500)


def validate_metadata(metadata, slug, version):
    object_value(metadata, 'metadata')
    required = {'schema_version', 'catalog_key', 'workflow_name', 'author', 'company',
                'version', 'description', 'uploaded_at', 'json_filename', 'source'}
    require(set(metadata) == required, 'metadata fields do not match schema version 1')
    require(type(metadata['schema_version']) is int and metadata['schema_version'] == 1,
            'unsupported metadata schema_version')
    require(metadata['catalog_key'] == f'{slug}/{version}', 'catalog_key must match directory')
    require(metadata['version'] == version, 'metadata version must match directory')
    for key, limit in [('workflow_name', 200), ('author', 200), ('company', 200),
                       ('description', 10000), ('json_filename', 180)]:
        text(metadata[key], key, limit, empty=(key == 'company'))
    require(FILENAME.fullmatch(metadata['json_filename']), 'unsafe json_filename')
    timestamp = metadata['uploaded_at']
    require(isinstance(timestamp, str), 'uploaded_at must be a UTC timestamp')
    try:
        parsed = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
        require(parsed.year >= 1000 and parsed.strftime('%Y-%m-%dT%H:%M:%SZ') == timestamp,
                'uploaded_at must be a canonical UTC timestamp')
    except ValueError as exc:
        raise InvalidCatalog('uploaded_at must be a valid UTC timestamp') from exc
    source = metadata['source']
    if source is not None:
        object_value(source, 'source')
        require(set(source) == {'catalog_url', 'id'}, 'invalid source fields')
        require(source['catalog_url'] == 'https://flowgraph-catalog.fbw-es.com/workflows/',
                'unrecognized migration source')
        require(isinstance(source['id'], str) and re.fullmatch(r'[1-9][0-9]{0,18}', source['id']),
                'invalid source ID')
    return metadata


def validate_catalog(root):
    directory = root / 'workflows'
    require(directory.is_dir() and not directory.is_symlink(), 'missing workflows directory')
    files = []
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), f'symlink is not allowed: {path}')
        if path.is_dir():
            parts = path.relative_to(directory).parts
            require(len(parts) <= 2, f'unexpected directory: {path}')
            require((SLUG if len(parts) == 1 else VERSION).fullmatch(parts[-1]),
                    f'unsafe workflow directory: {path}')
            if len(parts) == 1:
                require(any(path.iterdir()), f'empty workflow directory: {path}')
            else:
                require({p.name for p in path.iterdir()} == {'metadata.json', 'workflow.json'},
                        f'{path}: expected metadata.json and workflow.json only')
            continue
        parts = path.relative_to(directory).parts
        require(len(parts) == 3 and parts[2] in ('metadata.json', 'workflow.json'),
                f'unexpected workflow file: {path}')
        if parts[2] == 'metadata.json':
            files.append(path)
    require(files, 'catalog must contain at least one workflow')
    sources = set()
    keys = set()
    for path in files:
        slug, version, _ = path.relative_to(directory).parts
        try:
            metadata = validate_metadata(read_json(path), slug, version)
            require(metadata['catalog_key'].casefold() not in keys, 'duplicate catalog key')
            keys.add(metadata['catalog_key'].casefold())
            source = metadata['source']
            if source is not None:
                identity = (source['catalog_url'], source['id'])
                require(identity not in sources, 'duplicate source database ID')
                sources.add(identity)
            validate_workflow(read_json(path.with_name('workflow.json')))
        except InvalidCatalog as exc:
            raise InvalidCatalog(f'{path.relative_to(root)}: {exc}') from exc
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        count = validate_catalog(args.root.resolve())
    except (InvalidCatalog, OSError, RecursionError, OverflowError) as exc:
        print(f'Catalog validation failed: {exc}', file=sys.stderr)
        return 1
    print(f'Catalog validation passed: {count} workflows (static checks; no code executed).')
    return 0


if __name__ == '__main__':
    sys.exit(main())