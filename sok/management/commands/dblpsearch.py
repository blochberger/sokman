import pickle

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

import sok.management.commands.dblpimport as dblp

from sok.management.commands.snowball import semanticscholar
from sok.models import (
	Author,
	Publication,
	PublicationAuthor,
	PublicationSource,
	SearchTerm,
	SemanticScholar,
	Source,
)


class Command(BaseCommand):

	def log_success(self, msg: str):
		self.stdout.write(self.style.SUCCESS(msg))

	def log_info(self, msg: str, nl: bool = True):
		self.stdout.write(self.style.HTTP_INFO(msg), ending='\n' if nl else '')
		self.stdout.flush()

	def display_result(self, result: dblp.PublicationResult):
		self.stdout.write("")
		self.log_info(result.cite_key)
		if 0 < len(result.authors):
			self.stdout.write("  " + ", ".join([name for name in result.authors]))
		self.log_info("  " + result.title, nl=False)
		self.stdout.write(f" ({result.year})")

	def add_publication_source(
		self,
		publication: Publication,
		source: Source,
		search_term: SearchTerm,
	):
		publication_source, created = PublicationSource.objects.get_or_create(
			source=source,
			publication=publication,
			search_term=search_term,
		)
		if created:
			self.log_success(f"Assigned source '{source}' to publication '{publication}' with search term '{search_term}'")
		else:
			self.log_info(f"Source '{source}' already assigned to publication '{publication}' with search term '{search_term}'")

	@transaction.atomic
	def store_result(
		self,
		result: dblp.PublicationResult,
		source: Source,
		search_term: SearchTerm,
		paper_id: Optional[str],
	) -> Publication:

		# Store Authors
		authors: List[Author] = []
		for name in result.authors:
			author, created = Author.objects.get_or_create(name=name)
			if created:
				self.log_success(f"Added author: {author}")
			else:
				self.log_info(f"Author '{author}' alreay known")
			authors.append(author)

		# Store Publication
		publication = Publication(
			cite_key=result.cite_key,
			title=result.title,
			year=result.year,
			peer_reviewed=result.is_peer_reviewed,
			first_page=result.first_page,
			last_page=result.last_page,
		)
		publication.full_clean()
		publication.save()
		self.log_success(f"Added publication: {publication}")

		# Assign authors to publication
		for position, author in enumerate(authors):
			publication_author, created = PublicationAuthor.objects.get_or_create(
				author=author,
				publication=publication,
				position=position,
			)
			if created:
				self.log_success(f"Assigned author '{author}' to publication '{publication}' at position {position}")
			else:
				self.log_info(f"Author '{author}' already assigned to publication '{publication}' at position '{position}'")

		if paper_id is not None:
			s, created = SemanticScholar.objects.get_or_create(paper_id=paper_id, publication=publication)
			if created:
				self.log_success(f"Added Semantic Scholar '{paper_id}' to publication '{publication}'")
			else:
				self.log_info(f"Semantic Scholar '{paper_id}' for publication '{publication}' is already known")

		self.add_publication_source(publication, source, search_term)
		return publication

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--reset-choices', action='store_true')
		parser.add_argument('--limit', type=int, default=1000, help="1 – 1000 (default: 1000)")
		parser.add_argument('term')

	def handle(self, *args, **options):
		try:
			limit: int = options['limit']
			if not (0 < limit <= 1000):
				raise CommandError(f"Invalid value for 'limit': {limit}; allowed range is 1 – 1000")
			reset_choices: bool = options['reset_choices']
			source = Source.objects.get(name='DBLP')

			path = Path('.choices.dblp.pickle')
			cache: Dict[str, Set[str]] = defaultdict(set)
			if reset_choices:
				path.unlink(missing_ok=True)
			elif path.exists():
				self.log_info("Loading previous choices (reset with --reset-choices)...", nl=False)
				with path.open('rb') as f:
					cache = pickle.load(f)
				self.log_success("done")

			self.log_info("Querying DBLP... ", nl=False)
			query, results, total = dblp.PublicationResult.from_search(options['term'], limit)
			self.log_success(f"done, found {len(results)}/{total} publication(s)")

			# Create search term
			search_term, created = SearchTerm.objects.get_or_create(name=query)
			if created:
				self.log_success(f"Created search term: {search_term}")

			# Add search term to existing entries
			cite_keys = {result.cite_key for result in results}
			existing: Set[str] = set()
			for publication in Publication.objects.filter(cite_key__in=cite_keys):
				existing.add(publication.cite_key)
				self.add_publication_source(publication, source, search_term)

			# Promt the user for importing new entries
			for result in results:
				# Skip existing entries
				if result.cite_key in existing.union(cache[query]):
					continue

				self.display_result(result)

				# TODO Add abstract from semantic scholar

				data: Dict[str, Any] = dict()
				if doi := result.doi:
					data = semanticscholar(doi)

				while True:
					choice = input("Import? [y/N], Show abstract? [a]: ").lower()
					if choice in {'y', 'yes'}:
						self.store_result(result, source, search_term, data.get('paperId', None))
						break
					elif choice in {'', 'n', 'no'}:
						# Store choice
						cache[query].add(result.cite_key)
						with path.open('wb') as f:
							pickle.dump(cache, f)
						break
					elif choice == 'a':
						if abstract := data.get('abstract', None):
							self.stdout.write(abstract)
		except KeyboardInterrupt:
			raise CommandError("Aborted.")
