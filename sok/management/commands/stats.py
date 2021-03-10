from typing import Set

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

import sok.management.commands.dblpimport as dblp

from sok.models import Publication, SearchTerm


class Command(BaseCommand):

	def echo(self, msg: str, bold=True):
		if bold:
			msg = self.style.HTTP_INFO(msg)
		self.stdout.write(msg)

	# BaseCommand

	def handle(self, *args, **options):
		publications_found: Set[str] = set()
		publications_peer_reviewed: Set[str] = set()
		publications_relevant: Set[str] = set()

		self.echo("Loading DBLP dump...")
		all_cite_keys = dblp.get_all_cite_keys(dblp.DUMP_PATH)

		for search_term in SearchTerm.objects.all():
			# DBLP search result
			self.echo(f"Searching DBLP for '{search_term}'")
			query, results, total = dblp.PublicationResult.from_search(search_term.name, 1000)
			for result in results:
				if result.cite_key not in all_cite_keys:
					continue
				publications_found.add(result.cite_key)
				if result.is_peer_reviewed:
					publications_peer_reviewed.add(result.cite_key)

			# Relevant publications
			for publication in Publication.objects.filter(
				publicationsource__search_term=search_term,
				exclusion_criteria__isnull=True,
			).distinct():
				publications_relevant.add(publication.cite_key)

		# Output
		self.echo(f"Total publications: {len(publications_found):4d}", bold=True)
		self.echo(f"- peer reviewed:    {len(publications_peer_reviewed):4d}", bold=True)
		self.echo(f"- relevant:         {len(publications_relevant):4d}", bold=True)
