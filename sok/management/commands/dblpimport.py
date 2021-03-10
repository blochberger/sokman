import html
import io
import pickle
import string
import xml.sax

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

import requests

from django.db import transaction
from django.core.management.base import BaseCommand, CommandParser, CommandError

from sok.models import (
	Author,
	Publication,
	PublicationAuthor,
	PublicationSource,
	SearchTerm,
	Source,
)


Attributes = xml.sax.xmlreader.AttributesImpl


PUBLICATIONS = {
	'article',
	'inproceedings',
	'proceedings',
	'book',
	'incollection',
	'phdthesis',
	'mastersthesis',
	'www',
	'person',
	'data',
}

CITE_KEY_PREFIX = 'DBLP:'
DUMP_PATH = Path('dblp') / 'dblp-2021-03-01.xml'


def strip_cite_key_prefix(value: str) -> str:
	if value.startswith(CITE_KEY_PREFIX):
		return value[len(CITE_KEY_PREFIX):]
	return value


def strip_issue_from_page(value: str) -> int:
	return int(''.join(c for c in value.split(':')[-1] if c in string.digits))


def clean_title(value: str) -> str:
	if value.endswith('.'):
		return value[:-1]
	return value


def parse_pages(raw: str) -> Tuple[int, int]:
	# Observed:
	# - '1-10'
	# - '1'
	# - '16:1-16:10'
	# - 'I-X, 1-66'
	# - '186-'

	pages = raw.split(', ')[-1].split('-')

	if 2 == len(pages):
		first, last = pages
		if last != '':
			return (strip_issue_from_page(first), strip_issue_from_page(last))
		else:
			pages = [first]

	if 1 == len(pages):
		page = strip_issue_from_page(pages[0])
		return (page, page)

	raise NotImplementedError(f"Unexpected value for <pages>: {raw}")


class FinishedParsing(Exception):
	pass


@dataclass(frozen=True)
class PublicationResult:
	key: str
	title: str
	year: int
	pages: Optional[Tuple[int, int]]
	authors: List[str] = field(default_factory=list)
	urls: List[str] = field(default_factory=list)

	@property
	def cite_key(self) -> str:
		return CITE_KEY_PREFIX + self.key

	@property
	def doi(self) -> Optional[str]:
		for url_str in self.urls:
			url = urlparse(url_str)
			if url.hostname is not None and url.hostname.endswith('doi.org'):
				return url.path[1:]  # Strip leading '/'
		return None

	@property
	def is_peer_reviewed(self) -> Optional[bool]:
		"""
		Heuristically determine whether a publication is peer reviewed.
		"""

		# Preprint on arXiv.org
		if self.key.startswith('journals/corr/abs-'):
			return False

		# Consider conference proceedings, journal articles, and dissertations
		# as peer reviewed.
		if any([
			self.key.startswith('phd/'),
			self.key.startswith('conf/'),
			self.key.startswith('journals/'),
		]):
			return True

		return None

	@property
	def first_page(self) -> Optional[int]:
		if self.pages is None:
			return None
		return self.pages[0]

	@property
	def last_page(self) -> Optional[int]:
		if self.pages is None:
			return None
		return self.pages[1]

	@classmethod
	def from_dump(cls, path: Path, keys: Set[str]) -> List['PublicationResult']:
		parser = xml.sax.make_parser()

		# Enable DTD parsing
		parser.setFeature(xml.sax.handler.feature_external_ges, True)

		handler = DBLPHandler(keys)
		parser.setContentHandler(handler)
		try:
			parser.parse(path)
		except FinishedParsing:
			pass  # Just a workaround to abort SAX parsing if all entries were found

		return handler.publications

	@classmethod
	def from_api(cls, key: str) -> 'PublicationResult':

		url = f"https://dblp.uni-trier.de/rec/{key}.xml"
		response = requests.get(url)
		response.raise_for_status

		parser = xml.sax.make_parser()
		handler = DBLPHandler({key})
		parser.setContentHandler(handler)
		try:
			parser.parse(io.BytesIO(response.content))
		except FinishedParsing:
			pass

		assert 1 == len(handler.publications)

		return handler.publications[0]

	@classmethod
	def from_search_hit(cls, hit: Dict[str, Any]) -> 'PublicationResult':
		info = hit['info']

		pages: Optional[Tuple[int, int]] = None
		if raw_pages := info.get('pages', None):
			pages = parse_pages(raw_pages)

		# A single author is not a list, d'oh.
		authors = info.get('authors', dict()).get('author', [])
		if type(authors) is not list:
			authors = [authors]

		# TODO Parse URLs ('ee')

		return cls(
			key=info['key'],
			title=clean_title(html.unescape(info['title'])),
			year=int(info['year']),
			pages=pages,
			authors=[html.unescape(author['text']) for author in authors],
		)

	@classmethod
	def from_search(
		cls,
		search_term: str,
		limit: int = 1000,
	) -> Tuple[str, List['PublicationResult'], int]:
		# see https://dblp.uni-trier.de/faq/13501473.html
		url = 'http://dblp.org/search/publ/api'
		response = requests.get(
			url,
			params={
				'q': search_term,
				'f': 0,
				'h': limit,
				'c': 0,
				'format': 'json',
			},
		)
		response.raise_for_status
		search_result = response.json()['result']
		hits = search_result['hits']
		results = [cls.from_search_hit(hit) for hit in hits['hit']]

		total = hits['@total']
		# TODO re-request if len(results) < hits_total

		return (search_result['query'], results, total)


@dataclass
class DBLPFullHandler(xml.sax.handler.ContentHandler):
	entries: Dict[str, str] = field(default_factory=dict)

	# ContentHandler

	def startElement(self, name: str, attributes: Attributes):
		if name in PUBLICATIONS:
			key = attributes.getValue('key')
			self.entries[key] = name


def get_all_cite_keys(path: Path) -> Set[str]:
	cache_path = path.with_suffix('.pickle')
	cache: Dict[str, str] = dict()
	if cache_path.exists():
		with cache_path.open('rb') as f:
			cache = pickle.load(f)
	else:
		parser = xml.sax.make_parser()

		# Enable DTD parsing
		parser.setFeature(xml.sax.handler.feature_external_ges, True)

		handler = DBLPFullHandler()
		parser.setContentHandler(handler)
		parser.parse(path)

		cache = handler.entries
		with cache_path.open('wb') as f:
			pickle.dump(cache, f)

	return {CITE_KEY_PREFIX + key for key in cache.keys()}


@dataclass
class DBLPHandler(xml.sax.handler.ContentHandler):
	key_queue: Set[str]
	tag_stack: List[str] = field(default_factory=list)
	publications: List[PublicationResult] = field(default_factory=list)
	key: Optional[str] = None
	author: Optional[str] = None
	authors: List[Author] = field(default_factory=list)
	title: Optional[str] = None
	year: Optional[int] = None
	pages: Optional[Tuple[int, int]] = None
	urls: List[str] = field(default_factory=list)

	@property
	def current_tag(self) -> str:
		assert 0 < len(self.tag_stack)
		return self.tag_stack[-1]

	@property
	def is_handling_publication(self) -> bool:
		return self.key is not None

	def startElement(self, name: str, attributes: Attributes):
		self.tag_stack.append(name)

		if name in PUBLICATIONS:
			self.startPublication(name, attributes)

		if not self.is_handling_publication:
			return

		if name == 'author':
			self.author = ''
		if name == 'title':
			self.title = ''

	def endElement(self, name: str):
		self.tag_stack.pop(-1)

		if self.is_handling_publication and name in PUBLICATIONS:
			self.endPublication()

		if name == 'author' and self.author is not None:
			self.authors.append(self.author)
			self.author = None

	def characters(self, content: Union[bytes, str]):
		assert isinstance(content, str)  # TODO Handle bytes?

		if not self.is_handling_publication:
			return

		if 'author' in self.tag_stack:
			assert self.author is not None
			self.author += content

		if 'title' in self.tag_stack:
			assert self.title is not None
			self.title += content

		if self.current_tag == 'ee':
			self.urls.append(content)

		if self.current_tag == 'year':
			assert self.year is None
			self.year = int(content)

		if self.current_tag == 'pages':
			assert self.pages is None
			self.pages = parse_pages(content)

	def startPublication(self, name: str, attributes: Attributes):
		assert name in PUBLICATIONS
		assert not self.is_handling_publication
		assert 'key' in attributes
		assert self.author is None
		assert 0 == len(self.authors)
		assert self.title is None
		assert self.year is None
		assert self.pages is None
		assert 0 == len(self.urls)

		key = attributes.getValue('key')
		if key not in self.key_queue:
			return  # This is not the publication you are looking for.

		self.key_queue.remove(key)
		self.key = key

	def endPublication(self):
		assert self.is_handling_publication
		assert self.author is None
		assert self.key is not None
		assert self.title is not None
		assert self.year is not None
		assert 0 < len(self.authors)

		title = self.title
		if title.endswith('.'):
			title = title[:-1]

		publication = PublicationResult(
			key=self.key,
			title=title,
			year=self.year,
			authors=self.authors,
			pages=self.pages,
			urls=self.urls,
		)
		self.publications.append(publication)

		self.key = None
		self.authors = []
		self.title = None
		self.year = None
		self.pages = None
		self.urls = []

		if 0 == len(self.key_queue):
			raise FinishedParsing


class Command(BaseCommand):

	def log_success(self, msg: str):
		self.stdout.write(self.style.SUCCESS(msg))

	def log_info(self, msg: str, nl: bool = True):
		self.stdout.write(self.style.HTTP_INFO(msg), ending='\n' if nl else '')
		self.stdout.flush()

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('--use-api', action='store_true', default=False)
		parser.add_argument('--search-term', default=None)
		parser.add_argument('keys', nargs='+')

	@transaction.atomic
	def handle(self, *args, **options):
		use_api = options['use_api']
		source = Source.objects.get(name='DBLP')

		search_term: Optional[SearchTerm] = None
		if name := options['search_term']:
			search_term, created = SearchTerm.objects.get_or_create(name=name)
			if created:
				self.log_success(f"Created search term: {search_term}")

		cite_keys: Set[str] = set()
		publications: List[Publication] = []
		for key in set(options['keys']):
			try:
				publication = Publication.objects.get(cite_key=key)
				publications.append(publication)
			except Publication.DoesNotExist:
				if not key.startswith(CITE_KEY_PREFIX):
					raise CommandError(f"Invalid cite key: {key}")
				cite_keys.add(strip_cite_key_prefix(key))

		if 0 < len(cite_keys):

			if use_api:
				self.log_info("Querying DBLP... ", nl=False)
			else:
				self.log_info(f"Parsing DBLP dump '{DUMP_PATH}'... ", nl=False)
			start = datetime.now()
			if use_api:
				results: List[PublicationResult] = []
				for key in cite_keys:
					result = PublicationResult.from_api(key)
					results.append(result)
			else:
				results = PublicationResult.from_dump(DUMP_PATH, cite_keys)
			end = datetime.now()
			duration = end - start
			self.log_success(f"done ({duration}).")

			for result in results:

				# Add authors to database
				authors: List[Author] = []
				for name in result.authors:
					author, created = Author.objects.get_or_create(name=name)
					if created:
						self.log_success(f"Added author: {author}")
					else:
						self.log_info(f"Author '{author}' alreay known")
					authors.append(author)

				# Add publication to database
				publication, created = Publication.objects.get_or_create(
					cite_key=result.cite_key,
					title=result.title,
					year=result.year,
					peer_reviewed=result.is_peer_reviewed,
					first_page=result.first_page,
					last_page=result.last_page,
					doi=result.doi,
				)
				if created:
					self.log_success(f"Added publication: {publication}")
				else:
					self.log_info(f"Publication '{publication}' already known")
				publications.append(publication)

				# Assign authors
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

		# Assign sources
		if search_term is not None:
			for publication in publications:
				publication_source, created = PublicationSource.objects.get_or_create(
					source=source,
					publication=publication,
					search_term=search_term,
				)
				if created:
					self.log_success(f"Assigned source '{source}' to publication '{publication}' with search term '{search_term}'")
				else:
					self.log_info(f"Source '{source}' already assigned to publication '{publication}' with search term '{search_term}'")
