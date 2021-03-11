from typing import Optional, Set, Tuple

from django.contrib import admin, messages
from django.db.models import Count, F, Q
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from .models import (
	Author,
	ExclusionCriterion,
	Publication,
	SearchTerm,
	SemanticScholar,
	Source,
	Tag,
)


# Filters


class PublicationVariantFilter(admin.SimpleListFilter):
	title = _("is variant")
	parameter_name = 'variant'

	def lookups(self, request: HttpRequest, model_admin) -> Tuple[Tuple[str, str], ...]:
		return (
			('yes', _("yes")),
			('no', _("no")),
		)

	def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
		if self.value() == 'yes':
			return queryset.filter(variant_of__isnull=False)
		if self.value() == 'no':
			return queryset.filter(variant_of__isnull=True)
		return queryset


class PublicationRelevanceFilter(admin.SimpleListFilter):
	title = _("is relevant")
	parameter_name = 'is_relevant'

	def lookups(self, request: HttpRequest, model_admin) -> Tuple[Tuple[str, str], ...]:
		return (
			('yes', _("yes")),
			('no', _("no")),
		)

	def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
		if self.value() == 'yes':
			return queryset.filter(exclusion_criteria__isnull=True)
		if self.value() == 'no':
			return queryset.filter(exclusion_criteria__isnull=False)
		return queryset


class PublicationStageFilter(admin.SimpleListFilter):
	title = _("stage")
	parameter_name = 'stage'

	def lookups(self, request: HttpRequest, model_admin) -> Tuple[Tuple[str, str], ...]:
		return (
			('primary', _("primary")),
			('secondary', _("secondary")),
			('tertiary', _("tertiary")),
			('excluded', _("excluded")),
			('-', _("-")),
		)

	def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
		if self.value() == 'excluded':
			return queryset.filter(exclusion_criteria__isnull=False)

		relevant = queryset.filter(exclusion_criteria__isnull=True)

		if self.value() == 'primary':
			return relevant.filter(sources__isnull=False)

		if self.value() == 'secondary':
			return relevant.filter(
				referenced_by__exclusion_criteria__isnull=True,
				referenced_by__sources__isnull=False,
				sources__isnull=True,
			)

		if self.value() == 'tertiary':
			return relevant.filter(
				references__exclusion_criteria__isnull=True,
				references__sources__isnull=False,
				sources__isnull=True,
			).exclude(
				referenced_by__exclusion_criteria__isnull=True,
				referenced_by__sources__isnull=False,
			)

		if self.value() == '-':
			ids: Set[int] = {
				publication.id
				for publication in queryset
				if publication.stage is None
			}
			return queryset.filter(id__in=ids)

		return queryset


class TagCategoryFilter(admin.SimpleListFilter):
	title = _("category")
	parameter_name = 'category'

	def lookups(self, request: HttpRequest, model_admin) -> Tuple[Tuple[str, str], ...]:
		return (
			(str(tag.pk), tag.name)
			for tag in Tag.objects.filter(implies__isnull=True)
		)

	def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
		if value := self.value():
			pk = int(value)
			category = Tag.objects.get(pk=pk)
			# TODO Make transitive?
			return queryset.filter(implies=category)
		return queryset


# Inlines


class AuthorPublicationsInline(admin.TabularInline):
	model = Author.publications.through
	extra = 0
	ordering = ['position']
	autocomplete_fields = ('publication',)


class ExclusionCriterionPublications(admin.TabularInline):
	model = ExclusionCriterion.publications.through
	extra = 0
	autocomplete_fields = ('publication',)


class PublicationAuthorsInline(admin.TabularInline):
	model = Publication.authors.through
	extra = 0
	ordering = ['position']
	autocomplete_fields = ('author',)


class PublicationSourcesInline(admin.TabularInline):
	model = Publication.sources.through
	extra = 0
	autocomplete_fields = ('source', 'search_term')


class PublicationCitationsInline(admin.TabularInline):
	verbose_name = "citation"
	model = Publication.referenced_by.through
	fk_name = 'reference'
	extra = 0
	ordering = ['identifier']
	autocomplete_fields = ('publication',)


class PublicationReferencesInline(admin.TabularInline):
	verbose_name = "reference"
	model = Publication.references.through
	fk_name = 'publication'
	extra = 0
	ordering = ['identifier']
	autocomplete_fields = ('reference',)


class PublicationTagsInline(admin.TabularInline):
	model = Publication.tags.through
	extra = 0
	autocomplete_fields = ('tag',)


class TagPublicationsInline(admin.TabularInline):
	model = Tag.publications.through
	extra = 0
	autocomplete_fields = ('publication',)


# Models


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
	list_display = ('name', 'publication_count', 'relevant_publication_count')
	search_fields = ('name',)
	inlines = (AuthorPublicationsInline,)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return Author.objects.annotate(
			publication_count=Count('publications', distinct=True),
			relevant_publication_count=Count(
				'publications',
				filter=Q(publications__exclusion_criteria__isnull=True),
				distinct=True,
			),
		)

	def publication_count(self, obj: Author) -> int:
		return obj.publication_count

	def relevant_publication_count(self, obj: Author) -> int:
		return obj.relevant_publication_count

	publication_count.short_description = "publications"
	publication_count.admin_order_field = 'publication_count'
	relevant_publication_count.short_description = "rel. publications"
	relevant_publication_count.admin_order_field = 'relevant_publication_count'


@admin.register(ExclusionCriterion)
class ExclusionCriteriaAdmin(admin.ModelAdmin):
	list_display = ('name', 'publication_count')
	search_fields = ('name',)
	inlines = (ExclusionCriterionPublications,)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return ExclusionCriterion.objects.annotate(publication_count=Count('publications'))

	def publication_count(self, obj: ExclusionCriterion) -> int:
		return obj.publication_count

	publication_count.short_description = "publications"
	publication_count.admin_order_field = 'publication_count'


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
	list_display = ('name', 'publication_count', 'total_publications')
	list_filter = (TagCategoryFilter,)
	search_fields = ('name',)
	autocomplete_fields = ('implies',)
	inlines = (TagPublicationsInline,)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return Tag.objects.annotate(publication_count=Count('publications'))

	#def _implied_by(self, obj: Tag) -> str:
	#	return ", ".join(map(str, obj.implied_by.order_by('name')))

	def publication_count(self, obj: Tag) -> int:
		return obj.publication_count

	publication_count.short_description = "publications"
	publication_count.admin_order_field = "publication_count"


@admin.register(SemanticScholar)
class SemanticScholarAdmin(admin.ModelAdmin):
	list_display = ('paper_id', 'publication')
	search_fields = ('paper_id', 'publication')
	autocomplete_fields = ('publication',)


@admin.register(SearchTerm)
class SearchTermAdmin(admin.ModelAdmin):
	list_display = ('name', 'publication_count')
	search_fields = ('name',)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return SearchTerm.objects.annotate(
			publication_count=Count(
				'publicationsource__publication',
				filter=Q(publicationsource__publication__exclusion_criteria__isnull=True),
				distinct=True,
			),
		)

	def publication_count(self, obj: SearchTerm) -> int:
		return obj.publication_count

	publication_count.short_description = "publications"
	publication_count.admin_order_field = 'publication_count'


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
	list_display = ('name', 'publication_count')
	search_fields = ('name',)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return Source.objects.annotate(
			publication_count=Count('publications', distinct=True),
		)

	def publication_count(self, obj: Source) -> int:
		return obj.publication_count

	publication_count.short_description = "publications"
	publication_count.admin_order_field = 'publication_count'


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
	search_fields = ('cite_key', 'doi', 'title')
	list_display = (
		#'cite_key',
		'title',
		'year',
		'citation_count',
		'references_count',
		'page_count',
		'stage',
		'classified',
	)
	list_filter = (
		PublicationStageFilter,
		PublicationRelevanceFilter,
		'classified',
		'peer_reviewed',
		PublicationVariantFilter,
		#'year',
		#'sources',
	)
	inlines = (
		PublicationAuthorsInline,
		PublicationReferencesInline,
		PublicationCitationsInline,
		PublicationSourcesInline,
		PublicationTagsInline,
	)
	autocomplete_fields = ('exclusion_criteria', 'variant_of')
	actions = ('cite',)

	def get_queryset(self, request: HttpRequest) -> QuerySet:
		return Publication.objects.annotate(
			citation_count=Count(
				'referenced_by',
				filter=Q(exclusion_criteria__isnull=True),
				distinct=True,
			),
			references_count=Count(
				'references',
				filter=Q(exclusion_criteria__isnull=True),
				distinct=True,
			),
			page_count=1 + F('last_page') - F('first_page'),
		)

	def citation_count(self, obj: Publication) -> int:
		return obj.citation_count

	def references_count(self, obj: Publication) -> int:
		return obj.references_count

	def page_count(self, obj: Publication) -> int:
		return obj.page_count

	def cite(self, request: HttpRequest, queryset: QuerySet):
		cite_keys = queryset.order_by('cite_key').values_list('cite_key', flat=True).distinct()
		cite_str = ", ".join(list(cite_keys))
		self.message_user(request, f"\\cite{{{cite_str}}}", level=messages.SUCCESS)

	citation_count.short_description = "citations"
	citation_count.admin_order_field = 'citation_count'
	references_count.short_description = "references"
	references_count.admin_order_field = 'references_count'
	page_count.short_description = "pages"
	page_count.admin_order_field = 'page_count'
