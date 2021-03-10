from typing import Set, Tuple

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Count, Q

from sok.models import Publication


class Command(BaseCommand):

	def echo(self, msg: str):
		self.stdout.write(msg)

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--min-citations', type=int, default=0)
		parser.add_argument('--pk', action='store_true')

	def graphviz(self, pk: bool, min_citations: int) -> None:
		publications = Publication.objects.filter(exclusion_criteria__isnull=True).annotate(
			citation_count=Count(
				'referenced_by',
				filter=Q(exclusion_criteria__isnull=True),
				distinct=True,
			),
		).filter(citation_count__gte=min_citations)

		self.echo("digraph G {")
		self.echo("\trankdir = RL;")

		graph: Set[Tuple[int, int]] = set()

		for publication in publications:

			if publication.stage != 'primary':
				continue

			for reference in publication.relevant_references:

				if reference not in publications:
					continue

				graph.add((publication.pk, reference.pk))
				if (reference.pk, publication.pk) in graph:
					self.stderr.write(self.style.ERROR(
						f"CYCLE: {publication.cite_key} <-> {reference.cite_key}"
					))

				if pk:
					self.echo(f'\t"{publication.pk}" -> "{reference.pk}";')
				else:
					self.echo(f'\t"{publication.cite_key}" -> "{reference.cite_key}";')

		self.echo("}")

	def handle(self, *args, **options) -> None:
		min_citations: int = options['min_citations']
		pk: bool = options['pk']
		self.graphviz(pk, min_citations)
