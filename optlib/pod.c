/*
 * Generated by ./misc/optlib2c from optlib/pod.ctags, Don't edit this manually.
 */
#include "general.h"
#include "parse.h"
#include "routines.h"
#include "field.h"
#include "xtag.h"


static void initializePodParser (const langType language CTAGS_ATTR_UNUSED)
{
	addLanguageOptscriptToHook (language, SCRIPT_HOOK_PRELUDE,
		"{{	/kindTable\n"
		"	[ /chapter /section /subsection /subsubsection ] def\n"
		"}}");
}

extern parserDefinition* PodParser (void)
{
	static const char *const extensions [] = {
		"pod",
		NULL
	};

	static const char *const aliases [] = {
		NULL
	};

	static const char *const patterns [] = {
		NULL
	};

	static kindDefinition PodKindTable [] = {
		{
		  true, 'c', "chapter", "chapters",
		},
		{
		  true, 's', "section", "sections",
		},
		{
		  true, 'S', "subsection", "subsections",
		},
		{
		  true, 't', "subsubsection", "subsubsections",
		},
	};
	static tagRegexTable PodTagRegexTable [] = {
		{"^=head([1-4])[ \t]+(.+)", "",
		"", ""
		"{{\n"
		"	\\2\n"
		"	kindTable \\1 0 get ?1 sub get\n"
		"	2 /start _matchloc\n"
		"	_tag _commit pop\n"
		"}}", NULL, false},
	};


	parserDefinition* const def = parserNew ("Pod");

	def->enabled       = true;
	def->extensions    = extensions;
	def->patterns      = patterns;
	def->aliases       = aliases;
	def->method        = METHOD_NOT_CRAFTED|METHOD_REGEX;
	def->useCork       = CORK_QUEUE;
	def->kindTable     = PodKindTable;
	def->kindCount     = ARRAY_SIZE(PodKindTable);
	def->tagRegexTable = PodTagRegexTable;
	def->tagRegexCount = ARRAY_SIZE(PodTagRegexTable);
	def->initialize    = initializePodParser;

	return def;
}
