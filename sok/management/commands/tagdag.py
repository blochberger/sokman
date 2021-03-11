import html

from typing import Optional, Set, Tuple

from django.core.management.base import BaseCommand, CommandParser

from sok.models import Publication, PublicationTag, Tag


class Command(BaseCommand):

	def echo(self, msg: str, nl: bool = True):
		self.stdout.write(msg, ending='\n' if nl else '')

	def add_node(
		self,
		node: Tag,
		publication: Optional[Publication] = None,
		threshold: int = 0,
		include_publications: bool = False,
	):
		publications = node.transitive_publications
		num = len(publications)

		if node.pk in self.nodes:
			return  # Already printed this node
		if num < threshold:
			return
		if not (publication is None or publication in publications):
			return

		name = html.escape(node.name)
		self.echo(f"\tT{node.pk} [")
		self.echo(f'\t\tlabel="{name}', nl=False)
		implicit: bool = False
		if publication is None:
			if include_publications:
				pubs = ','.join([str(t.pk) for t in publications])
				self.echo(f"|{{{num}|{pubs}}}", nl=False)
			else:
				self.echo(f"|{num}", nl=False)
		else:
			try:
				rel = PublicationTag.objects.get(publication=publication, tag=node)
				if comment := rel.comment:
					comment = html.escape(rel.comment)
					self.echo(f"|{comment}", nl=False)
			except PublicationTag.DoesNotExist:
				implicit = True
		self.echo('",')
		if 0 == num:
			self.echo("\t\tcolor=red,")
		if implicit:
			self.echo("\t\tcolor=gainsboro,")
			self.echo("\t\tfontcolor=gray,")
		self.echo("\t];")

		self.nodes.add(node.pk)
		for predecessor in node.implied_by.all():
			self.add_node(predecessor, publication, threshold, include_publications)

	def add_edge(self, node: Tag):
		for predecessor in node.implied_by.all():
			if predecessor.pk not in self.nodes:
				continue
			edge = (predecessor.pk, node.pk)
			if edge in self.graph:
				continue
			if edge[::-1] in self.graph:
				self.stderr.write(self.style.ERROR(f"CYCLE: '{node}' <-> '{predecessor}'"))
			self.graph.add(edge)
			self.echo(f"\tT{predecessor.pk} -> T{node.pk};")
			self.add_edge(predecessor)

	def graphviz(
		self,
		root: Optional[Tag] = None,
		publication: Optional[Publication] = None,
		threshold: int = 0,
		include_publications: bool = False,
	):
		self.echo("digraph G {")
		self.echo("\trankdir = RL;")
		self.echo("\tnode [shape=record];")

		# Add nodes
		if root is None:
			for tag in Tag.objects.filter(implies__isnull=True):
				self.add_node(tag, publication, threshold, include_publications)
		else:
			self.add_node(root, publication, threshold, include_publications)

		# Add edges
		if root is None:
			for tag in Tag.objects.filter(implies__isnull=True):
				self.add_edge(tag)
		else:
			self.add_edge(root)

		self.echo("}")

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--root', default=None)
		parser.add_argument('--include-publications', action='store_true')
		parser.add_argument('--threshold', type=int, default=0)
		parser.add_argument('publication', nargs='?')

	def handle(self, *args, **options) -> None:
		include_publications: bool = options['include_publications']
		threshold: int = options['threshold']

		root: Optional[Tag] = None
		if tag_name := options.get('root', None):
			root = Tag.objects.get(name=tag_name)

		publication: Optional[Publication] = None
		if cite_key := options.get('publication', None):
			publication = Publication.objects.get(cite_key=cite_key)

		self.graph: Set[Tuple[int, int]] = set()
		self.nodes: Set[int] = set()
		self.graphviz(root, publication, threshold, include_publications)
