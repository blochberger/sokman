import hashlib
import json
import pickle

from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Set

import requests

from django.core.management.base import BaseCommand, CommandParser, CommandError
from tqdm import tqdm

from sok.models import (
	Author,
	Publication,
	PublicationAuthor,
	PublicationReference, 
	PublicationSource,
	SemanticScholar,
	Source,
)


def semanticscholar(identifier: str, include_unknown_references: bool = False) -> Dict[str, Any]:
	"""
	Retrieve information from the Semantic Scholar API.

	The identifier can be a DOI or the Semantic Scholar paper ID.

	See: https://api.semanticscholar.org
	"""

	url = f'https://api.semanticscholar.org/v1/paper/{identifier}'
	params: Dict[str, Any] = dict()
	if include_unknown_references:
		params['include_unknown_references'] = 'true'
	response = requests.get(url, params=params)
	response.raise_for_status
	return response.json()


class Command(BaseCommand):

	def echo(self, msg: str, bold: bool = False, nl: bool = True):
		if bold:
			msg = self.style.HTTP_INFO(msg)
		tqdm.write(msg, end='\n' if nl else '')
		#self.stdout.write(msg, ending='\n' if nl else '')

	def warn(self, msg: str):
		self.echo(self.style.WARNING(msg))

	def add_reference(
		self,
		publication: Publication,
		reference: Publication,
		is_reference: bool = True,
	):
		try:
			rel = PublicationReference.objects.get(
				publication=publication,
				reference=reference,
			)
			if is_reference:
				self.echo(f"Reference already known: {rel.identifier} {reference}")
			else:
				self.echo(f"Citation already known: {rel.identifier} {publication}")
		except PublicationReference.DoesNotExist:
			rel = PublicationReference(
				publication=publication,
				reference=reference,
			)
			rel.full_clean()
			rel.save()
			if is_reference:
				self.echo(f"Added reference: {reference}")
			else:
				self.echo(f"Added citation: {publication}")

	def display(self, obj: Dict[str, Any]):
		self.echo("")
		authors = [author['name'] for author in obj['authors']]
		title = obj['title']
		self.echo("  " + ", ".join(authors))
		self.echo(f"  {title}", bold=True, nl=False)
		if year := obj.get('year', None):
			self.echo(f" ({year})")
		else:
			self.echo("")
		if venue := obj.get('venue', None):
			self.echo(f"  {venue}")
		if doi := obj.get('doi', None):
			self.echo(f"  {doi}")
		if paper_id := obj.get('paperId', None):
			self.echo(f"  {paper_id}")

	def get_identifier(self, obj: Dict[str, Any]) -> str:
		if paper_id := obj.get('paperId', None):
			return paper_id
		raw = json.dumps(obj, sort_keys=True)
		hasher = hashlib.blake2b()
		hasher.update(raw.encode())
		return hasher.hexdigest()

	def handle_objs(
		self,
		base: Publication,
		objs: List[Dict[str, Any]],
		is_reference: bool,
	):
		title = "Reference" if is_reference else "Citation"
		if 0 < len(objs):
			self.echo(f"--- {title}s ---")
		publications: List[Publication] = []
		for obj in tqdm(objs, unit=title.lower()):
			if paper_id := obj.get('paperId', None):
				try:
					existing = SemanticScholar.objects.get(paper_id=paper_id)
					if is_reference:
						self.add_reference(base, existing.publication)
					else:
						self.add_reference(existing.publication, base, is_reference)
					continue
				except SemanticScholar.DoesNotExist:
					if doi := obj.get('doi', None):
						try:
							publication = Publication.objects.get(doi=doi)
							new = SemanticScholar(paper_id=paper_id, publication=publication)
							new.full_clean()
							new.save()
							self.echo(f"New Semantic Scholar entry: {paper_id}")
							if is_reference:
								self.add_reference(base, new.publication)
							else:
								self.add_reference(new.publication, base, is_reference)
							continue
						except Publication.DoesNotExist:
							pass

			identifier = self.get_identifier(obj)
			if identifier in self.cache:
				continue

			self.display(obj)

			paper_id = obj.get('paperId', None)
			while True:
				self.echo("Ignore? [Y/n]", nl=False)
				if paper_id is not None:
					self.echo(", Show abstract [a]", nl=False)
				self.echo(": ")
				choice = input().lower()
				if choice in {'', 'y', 'yes'}:
					# Store choice
					self.cache.add(identifier)
					with self.cache_path.open('wb') as f:
						pickle.dump(self.cache, f)
					break
				elif choice in {'a'}:
					assert paper_id is not None
					data = semanticscholar(paper_id)
					if abstract := data.get('abstract', None):
						self.echo(abstract)
				elif choice in {'', 'n', 'no'}:
					# TODO Import?
					data = semanticscholar(paper_id)
					# Add authors to database
					authors: List[Author] = []
					first = True
					cite_key = ''
					for author in data.get('authors', []):
						name = author.get('name', '')
						author, created = Author.objects.get_or_create(name=name)
						if created:
							self.echo(f"Added author: {author}")
						else:
							self.echo(f"Author '{author}' alreay known")
						authors.append(author)
						if first:
							first = False
							if name.rindex(' ') > -1:
								cite_key = name[name.rindex(' '):]
							else:
								cite_key = name
								
					cite_key += str(data.get('year'))
					
					title = data.get('title', '')
					if title.index(' ') > -1:
						cite_key += title[:title.index(' ')]
					else:
						cite_key += title
						
					cite_key = cite_key.lower()
					
					# Add publication to database
					doi = None if data.get('doi', None) == "None" else data.get('doi', None)
					publication, created = Publication.objects.get_or_create(
						cite_key=cite_key,
						title=title,
						year=data.get('year', 0),
						peer_reviewed=False,
						doi=doi,
					)
					if created:
						self.echo(f"Added publication: {publication}")
					else:
						self.echo(f"Publication '{publication}' already known")
					publications.append(publication)

					# Assign authors
					for position, author in enumerate(authors):
						publication_author, created = PublicationAuthor.objects.get_or_create(
							author=author,
							publication=publication,
							position=position,
						)
						if created:
							self.echo(f"Assigned author '{author}' to publication '{publication}' at position {position}")
						else:
							self.echo(f"Author '{author}' already assigned to publication '{publication}' at position '{position}'")
					
					# Add to Semantic Scholar and link publications
					if doi:
						publication = Publication.objects.get(doi=doi)
						new = SemanticScholar(paper_id=paper_id, publication=publication)
						new.full_clean()
						new.save()
						self.echo(f"New Semantic Scholar entry: {paper_id}")
						if is_reference:
							self.add_reference(base, new.publication)
						else:
							self.add_reference(new.publication, base, is_reference)
						
					break

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--reset-choices', action='store_true')
		parser.add_argument('--no-references', action='store_true')
		parser.add_argument('--no-citations', action='store_true')

	def handle(self, *args, **options):
		reset_choices: bool = options['reset_choices']
		no_citations: bool = options['no_citations']
		no_references: bool = options['no_references']

		self.cache_path = Path('.choices.semanticscholar.pickle')
		self.cache: Set[str] = set()
		if reset_choices:
			self.cache_path.unlink(missing_ok=True)
		elif self.cache_path.exists():
			self.echo("Loading previous choices (reset with --reset-choices)...", nl=False)
			with self.cache_path.open('rb') as f:
				self.cache = pickle.load(f)
			self.echo("done", bold=True)

		publications = Publication.objects.filter(
			semanticscholar__isnull=False,
			exclusion_criteria__isnull=True,
		)
		try:
			for publication in tqdm(publications, unit="publication"):
				self.echo(f"=== Publication {publication} ===")
				for semantic in publication.semanticscholar_set.all():
					data = semanticscholar(semantic.paper_id)

					if not no_references:
						references: List[Dict[str, Any]] = data['references']
						self.handle_objs(publication, references, is_reference=True)

					if not no_citations:
						citations: List[Dict[str, Any]] = data['citations']
						self.handle_objs(publication, citations, is_reference=False)

					sleep(2)  # Throttle
		except KeyboardInterrupt:
			raise CommandError("Aborted.")
