/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#include <expat.h>
#include <stdio.h>
#include <string.h>
int main(void) {
  if (strcmp(XML_ExpatVersion(), "expat_2.10.0")) return 1;
  XML_Parser parser = XML_ParserCreateNS(NULL, '|');
  if (!parser) return 2;
  const char *xml = "<root xmlns='urn:profile'><child/></root>";
  int ok = XML_Parse(parser, xml, (int)strlen(xml), XML_TRUE) == XML_STATUS_OK;
  XML_ParserFree(parser);
  if (!ok) return 3;
  parser = XML_ParserCreate(NULL);
  if (!parser) return 4;
  ok = XML_Parse(parser, "<broken>", 8, XML_TRUE) == XML_STATUS_ERROR;
  XML_ParserFree(parser);
  if (!ok) return 5;
  puts("expat_2.10.0_real_parser=true");
  return 0;
}
