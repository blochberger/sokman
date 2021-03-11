from typing import Optional, Set

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.query import QuerySet


class Author(models.Model):
	name = models.CharField(max_length=255, unique=True)

	def __str__(self) -> str:
		return self.name


class Tag(models.Model):
	name = models.CharField(max_length=255, unique=True)
	criteria = models.TextField(blank=True)
	implies = models.ManyToManyField('Tag', related_name='implied_by', blank=True)

	@property
	def transitive_publications(self) -> Set['Publication']:
		publications: Set[Publication] = set(self.publications.filter(exclusion_criteria__isnull=True))
		for implied in self.implied_by.all():
			publications = publications.union(implied.transitive_publications)
		return publications

	@property
	def total_publications(self) -> int:
		return len(self.transitive_publications)

	def __str__(self) -> str:
		return self.name


class ExclusionCriterion(models.Model):
	name = models.CharField(max_length=255, unique=True)
	description = models.TextField(blank=True, default='')

	def __str__(self) -> str:
		return self.name

	class Meta:
		verbose_name_plural = "exclusion criteria"


class Source(models.Model):
	name = models.CharField(max_length=255, unique=True)

	def __str__(self) -> str:
		return self.name


class SearchTerm(models.Model):
	name = models.CharField(max_length=255, unique=True)

	def __str__(self) -> str:
		return self.name


class Publication(models.Model):
	cite_key = models.CharField(max_length=255, unique=True)
	title = models.CharField(max_length=255)
	year = models.PositiveSmallIntegerField()
	peer_reviewed = models.BooleanField(null=True, default=None)
	classified = models.BooleanField(default=False)
	first_page = models.PositiveSmallIntegerField(blank=True, null=True, default=None)
	last_page = models.PositiveSmallIntegerField(blank=True, null=True, default=None)
	doi = models.CharField(max_length=255, unique=True, blank=True, null=True, default=None)

	variant_of = models.ForeignKey(
		'Publication',
		on_delete=models.CASCADE,
		related_name='variants',
		blank=True,
		null=True,
	)

	authors = models.ManyToManyField(Author, related_name='publications', through='PublicationAuthor')
	sources = models.ManyToManyField(Source, related_name='publications', through='PublicationSource')
	references = models.ManyToManyField('Publication', related_name='referenced_by', through='PublicationReference', through_fields=('publication', 'reference'))
	exclusion_criteria = models.ManyToManyField(ExclusionCriterion, related_name='publications', blank=True)
	tags = models.ManyToManyField(Tag, related_name='publications', through='PublicationTag')

	@property
	def is_peer_reviewed_or_cited_by_peer_reviewed(self) -> bool:
		if self.peer_reviewed:
			return True
		for referenced_by in self.referenced_by.filter():
			if referenced_by.is_peer_reviewed_or_cited_by_peer_reviewed:
				return True
		return False

	@property
	def is_relevant(self) -> bool:
		return not self.exclusion_criteria.exists()

	@property
	def relevant_references(self) -> QuerySet:
		return self.references.filter(exclusion_criteria__isnull=True)

	@property
	def relevant_referenced_by(self) -> QuerySet:
		return self.referenced_by.filter(exclusion_criteria__isnull=True)

	@property
	def stage(self) -> Optional[str]:
		if not self.is_relevant:
			return 'excluded'

		# Directly found by search term
		if self.sources.exists():
			return 'primary'

		# Referenced by primary (backward snowballing)
		# TODO make transitive
		if self.referenced_by.filter(exclusion_criteria__isnull=True, sources__isnull=False):
			return 'secondary'

		# References a primary (forward snowballing)
		# TODO make transitive
		if self.references.filter(exclusion_criteria__isnull=True, sources__isnull=False):
			return 'tertiary'

		return None

	def __str__(self) -> str:
		return self.cite_key


class SemanticScholar(models.Model):
	paper_id = models.CharField(
		max_length=40,
		unique=True,
		validators=[
			RegexValidator(r'^[a-f0-9]{40}$'),
		],
	)
	publication = models.ForeignKey(Publication, on_delete=models.CASCADE)

	def __str__(self) -> str:
		return self.paper_id

	class Meta:
		verbose_name_plural = "semantic scholar"


# M:N Relationships


class PublicationAuthor(models.Model):
	publication = models.ForeignKey(Publication, on_delete=models.CASCADE)
	author = models.ForeignKey(Author, on_delete=models.CASCADE)
	position = models.PositiveSmallIntegerField()

	class Meta:
		unique_together = (('publication', 'author'), ('publication', 'position'))


class PublicationTag(models.Model):
	publication = models.ForeignKey(Publication, on_delete=models.CASCADE)
	tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
	comment = models.CharField(max_length=255, blank=True, null=True)

	class Meta:
		unique_together = (('publication', 'tag'),)


class PublicationSource(models.Model):
	publication = models.ForeignKey(Publication, on_delete=models.CASCADE)
	source = models.ForeignKey(Source, on_delete=models.CASCADE)
	search_term = models.ForeignKey(SearchTerm, on_delete=models.CASCADE)

	class Meta:
		unique_together = (('publication', 'source', 'search_term'),)


class PublicationReference(models.Model):
	publication = models.ForeignKey(Publication, on_delete=models.CASCADE)
	reference = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name='cited_by')
	identifier = models.CharField(max_length=255, blank=True, null=True, default=None)

	class Meta:
		unique_together = (('publication', 'reference'), ('publication', 'identifier'))
