"""Resolve explicit saved ComfyUI subgraph boundaries into namespaced editor nodes.

The node/widget converter still validates installed backend schemas. Definitions
are copied, never edited; unsupported promotion or bypass layouts fail closed.
"""
from copy import deepcopy


def link_table(value):
    result = {}
    for item in value:
        if isinstance(item, dict):
            keys = ('id', 'origin_id', 'origin_slot', 'target_id', 'target_slot', 'type')
            if not all(key in item for key in keys):
                raise ValueError('Saved workflow contains an incomplete link.')
            item = [item[key] for key in keys]
        if not isinstance(item, list) or len(item) < 6:
            raise ValueError('Saved workflow contains an unsupported link.')
        if str(item[0]) in result:
            raise ValueError('Saved workflow contains duplicate link IDs.')
        result[str(item[0])] = item
    return result


def expand_subgraphs(editor):
    definitions = editor.get('definitions') or {}
    if not isinstance(definitions, dict) or not isinstance(definitions.get('subgraphs', []), list):
        raise ValueError("This workflow needs ComfyUI's API export (subgraphs or unsupported editor data).")
    registry = {}
    for item in definitions.get('subgraphs', []):
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in registry:
            raise ValueError('Saved subgraphs need unique definition IDs. Use a ComfyUI API export.')
        registry[item['id']] = item
    nodes, links, literals = [], [], {}
    contexts, identifiers = {}, set()
    count = 0

    def context(graph, prefix='', parent=None, instance=None, ancestry=()):
        nonlocal count
        raw = graph.get('nodes', [])
        if not isinstance(raw, list) or any(not isinstance(n, dict) or type(n.get('id')) not in (str, int) for n in raw):
            raise ValueError('Saved workflow nodes need unique IDs.')
        lookup = {str(n['id']): n for n in raw}
        count += len(raw)
        if count > 3000 or prefix in contexts:
            raise ValueError('Expanded workflow has duplicate namespaces or too many nodes (maximum 3000).')
        if len(lookup) != len(raw):
            raise ValueError('Saved workflow nodes need unique IDs.')
        ctx = dict(graph=graph, prefix=prefix, parent=parent, instance=instance,
                   nodes=lookup, links=link_table(graph.get('links', [])), ancestry=ancestry)
        if parent is not None:
            input_id = str(graph.get('inputNode', {}).get('id'))
            for link in ctx['links'].values():
                if str(link[1]) == input_id:
                    specs = graph.get('inputs', [])
                    if (type(link[2]) is not int or not 0 <= link[2] < len(specs)
                            or link[0] not in specs[link[2]].get('linkIds', [])):
                        raise ValueError('Subgraph input has an invalid saved boundary link.')
        contexts[prefix] = ctx
        for node in raw:
            name = node.get('type')
            if name in registry:
                if node.get('mode', 0) != 0:
                    raise ValueError('Muted/bypassed subgraph instances require ComfyUI\'s API export or an exact queued snapshot.')
                if name in ancestry or len(ancestry) >= 12:
                    raise ValueError('Recursive or deeply nested subgraphs require a ComfyUI API export.')
                context(registry[name], prefix + str(node['id']) + ':', ctx, node, ancestry + (name,))
            else:
                identifier = prefix + str(node['id'])
                if identifier in identifiers or len(identifiers) >= 3000:
                    raise ValueError('Expanded workflow has duplicate IDs or too many nodes (maximum 3000).')
                identifiers.add(identifier)
        return ctx

    def promoted_value(instance, entry):
        declared = [item['widget']['name'] for item in instance.get('inputs', [])
                    if isinstance(item.get('widget'), dict) and isinstance(item['widget'].get('name'), str)]
        values = instance.get('widgets_values', [])
        if not isinstance(values, list) or len(values) != len(declared) or len(set(declared)) != len(declared):
            raise ValueError('Subgraph widget order is ambiguous. Use a ComfyUI API export.')
        named = dict(zip(declared, values))
        saved = instance.get('widgets_values_named')
        if saved is not None and saved != named:
            raise ValueError('Subgraph named and positional widget values disagree. Save it again in ComfyUI.')
        name = entry.get('widget', {}).get('name')
        if name not in named:
            return 'missing', None
        value = named[name]
        if type(value) not in (str, int, float, bool):
            raise ValueError('A promoted subgraph input needs a scalar widget or an explicit connection. Use an API export.')
        return 'literal', value

    def incoming(ctx, target, slot, entry):
        link = ctx['links'].get(str(entry.get('link')))
        if not link or str(link[3]) != str(target) or link[4] != slot:
            raise ValueError(f'Node {target}: invalid saved connection.')
        return link

    def resolve(ctx, source, slot, visited=()):
        marker = (ctx['prefix'], str(source), slot)
        if type(slot) is not int or slot < 0 or marker in visited:
            raise ValueError('Subgraph contains an invalid or circular boundary connection.')
        visited = (*visited, marker)
        graph = ctx['graph']
        if ctx['parent'] is not None and str(source) == str(graph.get('inputNode', {}).get('id')):
            specs = graph.get('inputs', [])
            entries = ctx['instance'].get('inputs', [])
            if slot >= len(specs) or slot >= len(entries) or specs[slot].get('name') != entries[slot].get('name'):
                raise ValueError('Subgraph input slots do not match their saved definition. Use an API export.')
            entry = entries[slot]
            if entry.get('link') is None:
                return promoted_value(ctx['instance'], entry)
            link = incoming(ctx['parent'], ctx['instance']['id'], slot, entry)
            return resolve(ctx['parent'], link[1], link[2], visited)
        node = ctx['nodes'].get(str(source))
        if not node:
            raise ValueError('Subgraph contains a missing connection source.')
        if node.get('type') not in registry:
            return 'link', [ctx['prefix'] + str(source), slot]
        child = contexts[ctx['prefix'] + str(source) + ':']
        outputs = child['graph'].get('outputs', [])
        if slot >= len(outputs) or len(outputs[slot].get('linkIds', [])) != 1:
            raise ValueError('Subgraph output routing is ambiguous. Use a ComfyUI API export.')
        link = child['links'].get(str(outputs[slot]['linkIds'][0]))
        if (not link or str(link[3]) != str(child['graph'].get('outputNode', {}).get('id'))
                or link[4] != slot):
            raise ValueError('Subgraph output has an invalid saved connection.')
        return resolve(child, link[1], link[2], visited)

    context(editor)
    for ctx in contexts.values():
        for original in ctx['nodes'].values():
            if original.get('type') in registry:
                continue
            node = deepcopy(original)
            node['id'] = ctx['prefix'] + str(original['id'])
            for slot, entry in enumerate(node.get('inputs', [])):
                if entry.get('link') is None:
                    continue
                link = incoming(ctx, original['id'], slot, entry)
                kind, value = resolve(ctx, link[1], link[2])
                if kind == 'link':
                    identifier = len(links) + 1
                    links.append([identifier, value[0], value[1], node['id'], slot, link[5]])
                    entry['link'] = identifier
                else:
                    entry['link'] = None
                    if kind == 'literal':
                        literals.setdefault(node['id'], {})[entry['name']] = value
            nodes.append(node)
    return {**editor, 'nodes': nodes, 'links': links, 'definitions': {}}, literals
