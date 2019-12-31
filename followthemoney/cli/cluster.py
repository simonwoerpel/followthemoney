import csv
import json
import click
import logging
from itertools import combinations

from followthemoney import model
from followthemoney.types import registry
from followthemoney.compare import compare
from followthemoney.cli.cli import cli
from followthemoney.cli.util import read_entity
from followthemoney.export.graph import edge_types

log = logging.getLogger(__name__)

DEFAULT_BLOCK_TYPES = (registry.name.name, registry.checksum.name,
                       registry.iban.name, registry.ip.name,
                       registry.email.name, registry.address.name)


class Pair(object):

    def __init__(self, left, right, score=None, decision=None):
        self.left = left
        self.right = right
        self._score = score
        self.decision = decision

    @property
    def score(self):
        if self._score is None:
            self._score = compare(model, self.left, self.right)
        return self._score

    def to_dict(self):
        return {
            'left': self.left.to_dict(),
            'right': self.right.to_dict(),
            'score': self.score,
            'decision': self.decision,
        }

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data):
        left = model.get_proxy(data.get('left'))
        right = model.get_proxy(data.get('right'))
        return cls(left, right, data.get('score'), data.get('decision'))

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))


def generate_blocks(infiles, block_types):
    blocks, entities = {}, {}
    for infile in infiles:
        while True:
            entity = read_entity(infile)
            if entity is None:
                break
            if not entity.schema.matchable:
                continue
            entity.context['source_file'] = infile.name
            entities[entity.id] = entity
            for prop, value in entity.itervalues():
                if prop.type.name not in block_types:
                    continue
                key = prop.type.node_id(value)
                if key not in blocks:
                    blocks[key] = []
                blocks[key].append(entity.id)
    log.info("Generated %d blocks from %d entities.",
             len(blocks), len(entities))
    return blocks, entities


@cli.command('cluster', help="Generate clusters from entities")
@click.option('-i', '--infile', type=click.File('r'), default='-')  # noqa
@click.option('-b', '--block-types', type=click.Choice(edge_types()),
              multiple=True, default=DEFAULT_BLOCK_TYPES,
              help="Property types to be used for blocking.")
def cluster(infile, block_types):
    try:
        blocks, entities = generate_blocks(infile, block_types)
        real_blocks = 0
        for key, ids in blocks.items():
            if len(ids) < 2:
                continue
            # print(key, entities)
            real_blocks += 1
        print(real_blocks)
    except BrokenPipeError:
        raise click.Abort()


@cli.command('pair-match', help="Generate pairs of potential matches")
@click.option('-i', '--infile', type=click.File('r'), default='-', multiple=True)  # noqa
@click.option('-o', '--outfile', type=click.File('w'), default='-')  # noqa
@click.option('-t', '--threshold', type=float, default=0.4)  # noqa
@click.option('-x', '--xref', is_flag=True, default=False)  # noqa
@click.option('-b', '--block-types', type=click.Choice(edge_types()),
              multiple=True, default=DEFAULT_BLOCK_TYPES,
              help="Property types to be used for blocking.")
def pair_match(infile, outfile, threshold, xref, block_types):
    try:
        blocks, entities = generate_blocks(infile, block_types)
        pairs = set()
        for key, ids in blocks.items():
            for (a, b) in combinations(ids, 2):
                if (a, b) in pairs:
                    continue
                ent_a = entities[a]
                ent_b = entities[b]
                if xref and ent_a.context['source_file'] == ent_b.context['source_file']:  # noqa
                    continue
                pair = Pair(ent_a, ent_b)
                pairs.add((a, b))
                if pair.score > threshold:
                    outfile.write(pair.to_json() + '\n')
    except BrokenPipeError:
        raise click.Abort()


@cli.command('pair-csv', help="Convert pair data to CSV")
@click.option('-i', '--infile', type=click.File('r'), default='-')  # noqa
@click.option('-o', '--outfile', type=click.File('w'), default='-')  # noqa
def pair_csv(infile, outfile):
    try:
        writer = csv.writer(outfile, dialect=csv.unix_dialect)
        writer.writerow(['score', 'decision',
                         'left_id', 'left_caption',
                         'left_dates', 'left_countries',
                         'right_id', 'right_caption',
                         'right_dates', 'right_countries'])
        while True:
            line = infile.readline()
            if not line:
                return
            pair = Pair.from_json(line)
            left = pair.left
            right = pair.right
            writer.writerow([
                pair.score,
                pair.decision,
                left.id,
                left.caption,
                registry.date.join(left.get_type_values(registry.date)),
                registry.country.join(left.get_type_values(registry.country)),
                right.id,
                right.caption,
                registry.date.join(right.get_type_values(registry.date)),
                registry.country.join(right.get_type_values(registry.country)),
            ])
    except BrokenPipeError:
        raise click.Abort()
