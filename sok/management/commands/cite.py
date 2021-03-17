from typing import List

from django.core.management.base import BaseCommand, CommandParser

from sok.models import Publication


class Command(BaseCommand):

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('pk', nargs='+', type=int)

	def handle(self, *args, **options):
		pks: List[int] = options['pk']
		publications = [Publication.objects.get(pk=pk) for pk in pks]
		cite_keys = [publication.cite_key for publication in publications]
		self.stdout.write(r"\cite{" + ",".join(cite_keys) + "}", ending='')
