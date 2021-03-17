from typing import Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from sok.models import Publication, PublicationTag, Tag


class Command(BaseCommand):
	"""
	Merges `rhs` into `lhs`.
	"""

	def echo(self, msg: str):
		self.stdout.write(msg)

	def success(self, msg: str):
		self.echo(self.style.SUCCESS(msg))

	def get_tag(self, value: str) -> Tag:
		try:
			pk = int(value)
			return Tag.objects.get(pk=pk)
		except ValueError:
			pass

		try:
			return Tag.objects.get(name=value)
		except Tag.DoesNotExist:
			pass

		return Tag.objects.get(name__icontains=value)

	def get_rel(self, publication: Publication, tag: Tag) -> Optional[PublicationTag]:
		try:
			return PublicationTag.objects.get(publication=publication, tag=tag)
		except PublicationTag.DoesNotExist:
			return None

	@transaction.atomic
	def merge(self, lhs: Tag, rhs: Tag, publication: Publication):
		assert lhs.pk != rhs.pk

		rhs_rel = PublicationTag.objects.get(publication=publication, tag=rhs)
		lhs_rel, created = PublicationTag.objects.get_or_create(
			publication=publication,
			tag=lhs,
		)

		changed = False
		if lhs_cmt := lhs_rel.comment:
			if rhs_cmt := rhs_rel.comment:
				if lhs_cmt != rhs_cmt:
					lhs_rel.cmt = f"{lhs_cmt}; {rhs_cmt}"
					changed = True
		else:
			lhs_rel.comment = rhs_rel.comment
			changed = True

		rhs.publications.remove(publication)

		if changed:
			lhs_rel.full_clean()
			lhs_rel.save()
			self.success(f"{lhs} <- {rhs} [{publication.cite_key}]: {lhs_rel.comment}")
		else:
			self.success(f"{lhs} <- {rhs} [{publication.cite_key}]")

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('lhs')
		parser.add_argument('rhs')

	def handle(self, *args, **options):
		lhs = self.get_tag(options['lhs'])
		rhs = self.get_tag(options['rhs'])

		if lhs == rhs:
			raise CommandError(f"Cannot merge tag with itself: {lhs}")

		for publication in rhs.publications.all():
			self.merge(lhs, rhs, publication)
