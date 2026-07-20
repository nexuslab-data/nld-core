import json
import os
import sys
from typing import Any

from nld.business import find_terms
from nld.parameters.execution_params_def import ExecutionParameterDefinition
from nld.service import EntityTypeNames, FileOutputService
from nld.task import BaseRunStatus, StandardTask
from nld.task.context import NldExecutionContext

BUSINESS_DICTIONARY_FIND_FILE_NAME = "business_dictionary_find.json"


class BusinessDictionaryFindTask(StandardTask):
    """Look up business dictionary terms and emit the results as JSON.

    The scope flags (`match_name`, `match_synonym`, `match_related`) control
    which Term fields participate in the match. At least one scope must be
    enabled; defaults to name-only matching.
    """

    init_params = [
        ExecutionParameterDefinition(name="term", mandatory=True),
        ExecutionParameterDefinition(name="synonym", mandatory=False, data_type="bool"),
        ExecutionParameterDefinition(
            name="related_terms",
            mandatory=False,
            data_type="bool",
        ),
        ExecutionParameterDefinition(name="namespace", mandatory=False),
        ExecutionParameterDefinition(
            name="output",
            mandatory=False,
            data_type="bool",
        ),
        ExecutionParameterDefinition(
            name="override_output_folder_path",
            mandatory=False,
        ),
    ]
    run_params = []

    def __init__(
        self,
        term: str,
        synonym: bool = False,
        related_terms: bool = False,
        namespace: str | None = None,
        output: bool = False,
        override_output_folder_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.execution_context = NldExecutionContext.require_current()
        self.namespace = namespace
        self.output = output
        self.override_output_folder_path = override_output_folder_path
        self.query = term
        self.scope_name = True
        self.scope_related = related_terms
        self.scope_synonym = synonym

    def run(self, **kwargs: Any) -> bool:
        run_status = BaseRunStatus.SUCCESS.value

        self.execution_context.load_entities(
            entity_types=[EntityTypeNames.BUSINESS_DICTIONARY]
        )
        registry = self.execution_context.entity_registry

        matches = find_terms(
            registry=registry,
            query=self.query,
            match_name=self.scope_name,
            match_synonym=self.scope_synonym,
            match_related=self.scope_related,
            namespace=self.namespace,
        )

        payload = {
            "query": self.query,
            "namespace": self.namespace or ".",
            "scope": {
                "term": self.scope_name,
                "synonym": self.scope_synonym,
                "related_terms": self.scope_related,
            },
            "matches": [match.model_dump() for match in matches],
        }

        if self.output or self.override_output_folder_path is not None:
            file_output_service = FileOutputService(
                root_folder_path=self.execution_context.get_nld_root_folder_path(),
                override_output_folder_path=self.override_output_folder_path,
            )
            file_output_service.write_json_file(
                file_name=BUSINESS_DICTIONARY_FIND_FILE_NAME,
                data=payload,
            )
            output_path = os.path.join(
                file_output_service.determine_output_folder_path(),
                BUSINESS_DICTIONARY_FIND_FILE_NAME,
            )
            self.log_info(
                f"Wrote {len(matches)} match(es) to {output_path}",
            )
        else:
            sys.stdout.write(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            )
            sys.stdout.flush()

        return run_status
