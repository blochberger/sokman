import requests

from django.core.management.base import BaseCommand, CommandError, CommandParser

import sok.management.commands.dblpimport as dblp


class Command(BaseCommand):

	# BaseCommand

	def add_arguments(self, parser: CommandParser):
		parser.add_argument('key')

	def handle(self, *args, **options):
		key = dblp.strip_cite_key_prefix(options['key'])
		url = f'https://dblp.uni-trier.de/rec/{key}.bib?param=0'
		response = requests.get(url)
		response.raise_for_status

		# The status does not necessarily indicate success, but returns an error
		# page instead.
		if 'application/x-bibtex' not in response.headers['Content-Type']:
			raise CommandError(url)

		self.stdout.write(response.content.decode())
