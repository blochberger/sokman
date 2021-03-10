from pprint import pprint
from time import sleep

from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

import sok.management.commands.dblpimport as dblp

from sok.management.commands.snowball import semanticscholar
from sok.models import Publication, PublicationReference, SemanticScholar


class Command(BaseCommand):

	def log_success(self, msg: str):
		self.stdout.write(self.style.SUCCESS(msg))

	def log_info(self, msg: str, nl: bool = True):
		self.stdout.write(self.style.HTTP_INFO(msg), ending='\n' if nl else '')
		self.stdout.flush()

	@transaction.atomic
	def fix_references(self) -> None:
		"""
		Create relevant references to masters of referenced variants.

		If mulitple variants of a publication exist, only the master variant is
		considered. However, relevant publications might reference a non-master
		master-variant, e. g., a preprint.

		This command adds references to the master-variant, even though this
		reference is not actually present in the publication. The reference
		identifier is marked with a star, e. g., '[1]*'.
		"""

		self.log_info("--- Searching for references to variants ---")
		for publication in Publication.objects.filter(variant_of__isnull=False):
			variant = publication.variant_of
			origs = PublicationReference.objects.filter(reference=publication)
			for orig in origs:
				if PublicationReference.objects.filter(reference=variant, publication=orig.publication).exists():
					continue
				fixed = PublicationReference(
					reference=variant,
					publication=orig.publication,
					identifier=('' if orig.identifier is None else orig.identifier) + "*",
				)
				try:
					fixed.full_clean()
					fixed.save()
					self.log_success(f"Added reference: {publication} -- {fixed.identifier} -> {variant}")
				except ValidationError as e:
					raise CommandError(f"{publication} -- {fixed.identifier} -> {variant}: {e}")

	def fix_dblp(self):
		self.log_info("--- Searching for entries not in the default DBLP dump ---")
		keys_in_db = set(
			Publication.objects.filter(
				cite_key__startswith=dblp.CITE_KEY_PREFIX
			).values_list('cite_key', flat=True).distinct()
		)
		keys_in_dump = dblp.get_all_cite_keys(dblp.DUMP_PATH)

		self.stdout.write(f"DB:   {len(keys_in_db):8d}")
		self.stdout.write(f"DBLP: {len(keys_in_dump):8d}")
		pprint(keys_in_db - keys_in_dump)

	def find_missing_dois(self):
		self.log_info("--- Searching for missing DOIs ---")
		publications = Publication.objects.filter(doi__isnull=True)
		keys = {
			dblp.strip_cite_key_prefix(cite_key)
			for cite_key in publications.values_list('cite_key', flat=True)
		}
		self.log_info("Parsing DBLP dump...")
		results = dblp.PublicationResult.from_dump(dblp.DUMP_PATH, keys)
		self.log_info("done")

		for result in results:
			if doi := result.doi:
				publication = publications.get(cite_key=result.cite_key)
				publication.doi = doi
				publication.full_clean()
				publication.save()
				self.log_success(f"Added DOI '{doi}' to publication: {publication}")

	def find_semanticscholar_ids(self):
		self.log_info("--- Searching for paper IDs on Semantic Scholar ---")
		publications = Publication.objects.filter(
			doi__isnull=False,
			semanticscholar__isnull=True,
		)
		for publication in publications:
			data = semanticscholar(publication.doi)

			paper_id = data['paperId']
			obj = SemanticScholar(paper_id=paper_id, publication=publication)
			obj.full_clean()
			obj.save()
			self.log_success(f"Set semanticscholar ID for publication '{publication}': {paper_id}")

			sleep(2)  # Throttle to avoid rate-limiting

	# BaseCommand

	def handle(self, *args, **options):
		self.fix_references()
		self.fix_dblp()
		self.find_missing_dois()
		self.find_semanticscholar_ids()
