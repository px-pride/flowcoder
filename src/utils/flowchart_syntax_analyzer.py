"""Flowchart syntax analyzer for Commands tab syntax check."""

from dataclasses import dataclass
from typing import List, Set, Tuple

from src.models import (
    Flowchart,
    PromptBlock,
    VariableBlock,
    BashBlock,
    BranchBlock,
    CommandBlock
)
from src.utils.variable_substitution import VariableSubstitution


@dataclass
class SyntaxIssue:
    level: str  # e.g., 'warning'
    message: str
    block_id: str
    block_name: str


class FlowchartSyntaxAnalyzer:
    """Analyzes a flowchart for variable initialization and schema issues."""

    def analyze(self, flowchart: Flowchart) -> List[SyntaxIssue]:
        issues: List[SyntaxIssue] = []
        defined_vars = self._collect_defined_variables(flowchart, issues)

        for block in flowchart.blocks.values():
            refs = self._collect_variable_references(block)
            undefined = refs - defined_vars
            if undefined:
                msg = (
                    "Uninitialized variables used: "
                    + ", ".join(sorted(undefined))
                )
                issues.append(SyntaxIssue(
                    level='warning',
                    message=msg,
                    block_id=block.id,
                    block_name=block.name
                ))

        return issues

    def _collect_defined_variables(
        self,
        flowchart: Flowchart,
        issues: List[SyntaxIssue]
    ) -> Set[str]:
        defined: Set[str] = set()

        for block in flowchart.blocks.values():
            if isinstance(block, VariableBlock) and block.variable_name:
                defined.add(block.variable_name)

            if isinstance(block, BashBlock) and block.capture_output:
                var_name = (block.output_variable or '').strip()
                if var_name:
                    defined.add(var_name)

            if isinstance(block, PromptBlock) and block.output_schema:
                schema_vars, warning = self._parse_prompt_schema(block)
                defined.update(schema_vars)
                if warning:
                    issues.append(warning)

        return defined

    def _collect_variable_references(self, block) -> Set[str]:
        texts: List[str] = []
        if isinstance(block, PromptBlock):
            texts.append(block.prompt or '')
        elif isinstance(block, VariableBlock):
            texts.append(block.variable_value or '')
        elif isinstance(block, BashBlock):
            texts.append(block.command or '')
        elif isinstance(block, BranchBlock):
            texts.append(block.condition or '')
        elif isinstance(block, CommandBlock):
            texts.append(block.arguments or '')

        refs: Set[str] = set()
        for text in texts:
            if text:
                refs.update(self._find_variable_refs(text))
        return refs

    def _find_variable_refs(self, text: str) -> Set[str]:
        return set(VariableSubstitution.VAR_PATTERN.findall(text))

    def _parse_prompt_schema(
        self,
        block: PromptBlock
    ) -> Tuple[Set[str], SyntaxIssue]:
        schema = block.output_schema
        if not isinstance(schema, dict):
            return set(), SyntaxIssue(
                level='warning',
                message='Structured output schema must be a JSON object.',
                block_id=block.id,
                block_name=block.name
            )

        schema_type = schema.get('type')
        props = schema.get('properties')
        if schema_type != 'object' or not isinstance(props, dict):
            return set(), SyntaxIssue(
                level='warning',
                message='Structured output schema should define type "object" with properties.',
                block_id=block.id,
                block_name=block.name
            )

        return set(props.keys()), None
