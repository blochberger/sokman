from typing import Set, Tuple

from django.core.management.base import BaseCommand, CommandParser

from sok.models import Tag


class Command(BaseCommand):

	def echo(self, msg: str):
		self.stdout.write(msg)

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--root', default='CAPI Misuse')

	def _graphviz(self, root: Tag) -> None:
		for tag in root.implied_by.all():
			edge = (tag.pk, root.pk)
			if edge in self.graph:
				continue
			if edge[::-1] in self.graph:
				self.stderr.write(self.style.ERROR(f"CYCLE: '{root}' <-> '{tag}'"))
			self.graph.add(edge)
			self._graphviz(tag)
			self.echo(f'\t"{tag}" -> "{root}";')

	def graphviz(self, root: Tag) -> None:
		self.echo("digraph G {")
		self.echo("\trankdir = RL;")
		self._graphviz(root)
		self.echo("}")

	def handle(self, *args, **options) -> None:
		self.graph: Set[Tuple[int, int]] = set()
		root = Tag.objects.get(name=options['root'])
		self.graphviz(root)
