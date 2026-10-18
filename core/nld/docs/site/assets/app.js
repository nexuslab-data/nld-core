(function () {
  "use strict";

  var snapshot = window.NLD_DOCS_SNAPSHOT || {};
  /* Where this site reads its live state from. A site served by
     `nld docs serve` calls the local API; a published one reads a
     state.json refreshed by a scheduled job, or shows no state at all.
     Written beside the page so the same build serves from a laptop, a
     bucket or an internal host. */
  var siteConfig = window.NLD_DOCS_CONFIG || {};
  var contentEl = document.getElementById("content");
  var navEl = document.getElementById("nav");
  var searchInput = document.getElementById("search-input");

  var structureById = {};
  var flowById = {};
  var entitiesByType = snapshot.entities || {};
  var namespaceByName = {};
  var searchIndex = [];
  var liveState = null;
  var liveStateError = null;
  var liveStateLoaded = false;
  var stateApiEnabled = null;
  var termsByDictionary = {};
  var lineageView = { scale: 1, x: 0, y: 0 };
  var LINEAGE_STORAGE_KEY = "nld-docs-lineage";
  var lineageOptions = {
    selection: "",
    groupDepth: 1,
    collapsedGroups: {},
    isolate: false,
    direction: "both",
    depth: 0,
    structuresOnly: false,
  };
  var searchSelection = -1;
  var filterCounter = 0;

  /* ---------------------------------------------------------------- utils */

  function escapeHtml(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function encodeSegment(value) {
    return encodeURIComponent(String(value === undefined ? "" : value));
  }

  function isEmpty(value) {
    if (value === null || value === undefined || value === "") {
      return true;
    }
    if (Array.isArray(value)) {
      return value.length === 0;
    }
    if (typeof value === "object") {
      return Object.keys(value).length === 0;
    }
    return false;
  }

  function formatDate(value) {
    if (!value) {
      return "—";
    }
    var parsed = new Date(value);
    if (isNaN(parsed.getTime())) {
      return String(value);
    }
    return parsed.toISOString().replace("T", " ").slice(0, 19) + " UTC";
  }

  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) {
      return "—";
    }
    var total = Math.round(Number(seconds));
    if (total < 60) {
      return total + "s";
    }
    if (total < 3600) {
      return Math.floor(total / 60) + "m " + (total % 60) + "s";
    }
    if (total < 86400) {
      return Math.floor(total / 3600) + "h " + Math.floor((total % 3600) / 60) + "m";
    }
    return Math.floor(total / 86400) + "d " + Math.floor((total % 86400) / 3600) + "h";
  }

  function namespaceLabel(namespace) {
    return !namespace || namespace === "." ? "root" : namespace;
  }

  function splitId(nodeId) {
    var value = String(nodeId === undefined || nodeId === null ? "" : nodeId);
    var separator = value.lastIndexOf(".");
    if (separator === -1) {
      return { namespace: null, name: value };
    }
    return { namespace: value.slice(0, separator), name: value.slice(separator + 1) };
  }

  /* Every identifier is displayed as "[namespace] name": the namespace reads
     as a tag and the asset name stays scannable in long lists. */
  function displayId(nodeId) {
    var parts = splitId(nodeId);
    return (
      (parts.namespace ? '<span class="ns-tag">[' + escapeHtml(parts.namespace) + "]</span> " : "") +
      escapeHtml(parts.name)
    );
  }

  /* ------------------------------------------------------------- markdown */

  function safeHref(url) {
    var trimmed = String(url || "").trim();
    var scheme = /^([a-z][a-z0-9+.-]*):/i.exec(trimmed);
    if (scheme && !/^(https?|mailto)$/i.test(scheme[1])) {
      return null;
    }
    return trimmed;
  }

  function renderInline(text) {
    var out = escapeHtml(text);
    out = out.replace(/`([^`]+)`/g, '<code class="inline">$1</code>');
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/\[([^\]]+)\]\(((?:[^()\s]|\([^()]*\))+)\)/g, function (match, label, url) {
      var href = safeHref(url);
      if (href === null) {
        return label;
      }
      return '<a href="' + href + '" rel="noreferrer">' + label + "</a>";
    });
    return out;
  }

  function isTableRow(line) {
    return /^\s*\|.*\|\s*$/.test(line);
  }

  function isTableSeparator(line) {
    return /^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$/.test(line);
  }

  function splitTableRow(line) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map(function (cell) {
        return cell.trim();
      });
  }

  function renderTable(lines) {
    var header = splitTableRow(lines[0]);
    var rows = lines.slice(2).map(splitTableRow);
    return (
      "<table><thead><tr>" +
      header
        .map(function (cell) {
          return "<th>" + renderInline(cell) + "</th>";
        })
        .join("") +
      "</tr></thead><tbody>" +
      rows
        .map(function (row) {
          return (
            "<tr>" +
            header
              .map(function (cell, index) {
                return "<td>" + renderInline(row[index] || "") + "</td>";
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody></table>"
    );
  }

  function renderMarkdown(text) {
    if (!text) {
      return "";
    }
    var lines = String(text).replace(/\r\n/g, "\n").split("\n");
    var html = [];
    var listType = null;
    var inCode = false;
    var codeBuffer = [];
    var paragraph = [];

    function flushParagraph() {
      if (paragraph.length) {
        html.push("<p>" + renderInline(paragraph.join(" ")) + "</p>");
        paragraph = [];
      }
    }

    function flushList() {
      if (listType) {
        html.push("</" + listType + ">");
        listType = null;
      }
    }

    for (var index = 0; index < lines.length; index += 1) {
      var line = lines[index];

      if (/^```/.test(line.trim())) {
        if (inCode) {
          html.push("<pre><code>" + escapeHtml(codeBuffer.join("\n")) + "</code></pre>");
          codeBuffer = [];
          inCode = false;
        } else {
          flushParagraph();
          flushList();
          inCode = true;
        }
        continue;
      }

      if (inCode) {
        codeBuffer.push(line);
        continue;
      }

      if (isTableRow(line) && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
        flushParagraph();
        flushList();
        var tableLines = [line, lines[index + 1]];
        var cursor = index + 2;
        while (cursor < lines.length && isTableRow(lines[cursor])) {
          tableLines.push(lines[cursor]);
          cursor += 1;
        }
        html.push(renderTable(tableLines));
        index = cursor - 1;
        continue;
      }

      var heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        flushParagraph();
        flushList();
        var level = Math.min(heading[1].length + 1, 6);
        html.push("<h" + level + ">" + renderInline(heading[2]) + "</h" + level + ">");
        continue;
      }

      var bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
      if (bullet) {
        flushParagraph();
        if (listType !== "ul") {
          flushList();
          html.push("<ul>");
          listType = "ul";
        }
        html.push("<li>" + renderInline(bullet[1]) + "</li>");
        continue;
      }

      var ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (listType !== "ol") {
          flushList();
          html.push("<ol>");
          listType = "ol";
        }
        html.push("<li>" + renderInline(ordered[1]) + "</li>");
        continue;
      }

      var quote = /^\s*>\s?(.*)$/.exec(line);
      if (quote) {
        flushParagraph();
        flushList();
        html.push("<blockquote>" + renderInline(quote[1]) + "</blockquote>");
        continue;
      }

      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }

      paragraph.push(line.trim());
    }

    if (inCode && codeBuffer.length) {
      html.push("<pre><code>" + escapeHtml(codeBuffer.join("\n")) + "</code></pre>");
    }
    flushParagraph();
    flushList();
    return '<div class="markdown">' + html.join("\n") + "</div>";
  }

  /* --------------------------------------------------------------- render */

  function card(title, body) {
    return (
      '<section class="card">' +
      (title ? "<h2>" + escapeHtml(title) + "</h2>" : "") +
      body +
      "</section>"
    );
  }

  function cardWithBadge(title, badgeHtml, body) {
    return (
      '<section class="card">' +
      "<h2>" +
      escapeHtml(title) +
      " " +
      (badgeHtml || "") +
      "</h2>" +
      body +
      "</section>"
    );
  }

  function emptyBlock(message) {
    return '<div class="empty">' + escapeHtml(message) + "</div>";
  }

  function table(headers, rows) {
    if (!rows.length) {
      return emptyBlock("Nothing to show.");
    }
    var head = headers
      .map(function (header) {
        return "<th>" + escapeHtml(header) + "</th>";
      })
      .join("");
    var body = rows
      .map(function (row) {
        return (
          "<tr>" +
          row
            .map(function (cell) {
              return "<td>" + cell + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function tableWithMeta(headers, rows) {
    if (!rows.length) {
      return emptyBlock("Nothing to show.");
    }
    var head = headers
      .map(function (header) {
        return "<th>" + escapeHtml(header) + "</th>";
      })
      .join("");
    var body = rows
      .map(function (row) {
        var search = [row.name, row.namespace, row.search]
          .filter(function (value) {
            return value !== null && value !== undefined && value !== "";
          })
          .join(" ")
          .toLowerCase();
        return (
          '<tr data-namespace="' +
          escapeHtml(row.namespace === null || row.namespace === undefined ? "" : row.namespace) +
          '" data-kind="' +
          escapeHtml(row.kind || "") +
          '" data-search="' +
          escapeHtml(search) +
          '">' +
          row.cells
            .map(function (cell) {
              return "<td>" + cell + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function namespaceOptions(values) {
    var seen = {};
    values.forEach(function (value) {
      seen[value === null || value === undefined ? "." : value] = true;
    });
    return Object.keys(seen).sort();
  }

  /* A namespace matches a picker value when it is that namespace, one of
     its descendants, or simply contains the typed text: typing "wttj"
     narrows to wttj, wttj.raw, wttj.extraction… as you type. */
  function namespaceMatches(namespace, value) {
    var needle = String(value || "").trim().toLowerCase();
    if (!needle) {
      return true;
    }
    var candidate = (namespace === null || namespace === undefined || namespace === "" ? "." : namespace).toLowerCase();
    if (needle === "." || needle === "root") {
      return candidate === ".";
    }
    return candidate === needle || candidate.indexOf(needle + ".") === 0 || candidate.indexOf(needle) !== -1;
  }

  /* Type-ahead namespace picker: an input whose live option list narrows on
     every keystroke; picking an option fills the input, and the input value
     is what filters. */
  function namespacePicker(attribute, namespaces, value, placeholder) {
    return (
      '<span class="ns-picker" data-ns-options="' +
      escapeHtml(JSON.stringify(namespaces)) +
      '"><input type="text" ' +
      attribute +
      ' data-ns-input placeholder="' +
      escapeHtml(placeholder || "Namespace…") +
      '" value="' +
      escapeHtml(value || "") +
      '" autocomplete="off" spellcheck="false" />' +
      '<button type="button" class="ns-clear" data-ns-clear title="Clear the namespace" aria-label="Clear the namespace">×</button>' +
      '<div class="ns-options" hidden></div></span>'
    );
  }

  function attachNamespacePickers() {
    var pickers = document.querySelectorAll(".ns-picker");
    for (var index = 0; index < pickers.length; index += 1) {
      (function (picker) {
        var input = picker.querySelector("[data-ns-input]");
        var list = picker.querySelector(".ns-options");
        var clear = picker.querySelector("[data-ns-clear]");
        var namespaces = [];
        try {
          namespaces = JSON.parse(picker.getAttribute("data-ns-options") || "[]");
        } catch (error) {
          namespaces = [];
        }
        var selection = -1;

        function notify() {
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function close() {
          list.hidden = true;
          list.innerHTML = "";
          selection = -1;
        }

        function open() {
          var needle = input.value.trim().toLowerCase();
          var matches = namespaces.filter(function (namespace) {
            return !needle || namespaceLabel(namespace).toLowerCase().indexOf(needle) !== -1;
          });
          selection = -1;
          if (!matches.length) {
            list.innerHTML = '<div class="ns-option muted">No namespace matches</div>';
            list.hidden = false;
            return;
          }
          list.innerHTML = matches
            .slice(0, 40)
            .map(function (namespace) {
              return (
                '<div class="ns-option" data-ns-value="' +
                escapeHtml(namespace) +
                '">' +
                highlight(namespaceLabel(namespace), needle) +
                "</div>"
              );
            })
            .join("") + (matches.length > 40 ? '<div class="ns-option muted">' + (matches.length - 40) + " more…</div>" : "");
          list.hidden = false;
        }

        function pick(namespace) {
          input.value = namespace === "." ? "." : namespace;
          close();
          notify();
        }

        function move(delta) {
          var options = list.querySelectorAll("[data-ns-value]");
          if (!options.length) {
            return;
          }
          selection = (selection + delta + options.length) % options.length;
          for (var optionIndex = 0; optionIndex < options.length; optionIndex += 1) {
            options[optionIndex].className = optionIndex === selection ? "ns-option selected" : "ns-option";
          }
          options[selection].scrollIntoView({ block: "nearest" });
        }

        input.addEventListener("focus", open);
        input.addEventListener("input", open);
        input.addEventListener("keydown", function (event) {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            if (list.hidden) {
              open();
            }
            move(1);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          } else if (event.key === "Enter") {
            var options = list.querySelectorAll("[data-ns-value]");
            if (selection >= 0 && options[selection]) {
              event.preventDefault();
              pick(options[selection].getAttribute("data-ns-value"));
            } else {
              close();
            }
          } else if (event.key === "Escape") {
            close();
          }
        });
        list.addEventListener("mousedown", function (event) {
          var option = event.target.closest ? event.target.closest("[data-ns-value]") : null;
          if (option) {
            event.preventDefault();
            pick(option.getAttribute("data-ns-value"));
          }
        });
        clear.addEventListener("click", function () {
          input.value = "";
          close();
          notify();
          input.focus();
        });
        document.addEventListener("click", function (event) {
          if (!picker.contains(event.target)) {
            close();
          }
        });
      })(pickers[index]);
    }
  }

  /* One toolbar filters the tables named in targetIds: a text box matching
     name and description, a namespace type-ahead and an optional kind
     drop-down. */
  function filterToolbar(targetIds, options) {
    filterCounter += 1;
    var html =
      '<div class="filter-toolbar" data-filter-targets="' +
      escapeHtml(targetIds.join(" ")) +
      '">' +
      '<input type="search" data-filter-text placeholder="' +
      escapeHtml(options.placeholder || "Filter by name or description…") +
      '" autocomplete="off" />';
    if (options.namespaces && options.namespaces.length) {
      html += namespacePicker("data-filter-namespace", options.namespaces, "", "Namespace…");
    }
    if (options.kinds && options.kinds.length) {
      html +=
        '<select data-filter-kind aria-label="Kind"><option value="">All kinds</option>' +
        options.kinds
          .map(function (kind) {
            return '<option value="' + escapeHtml(kind) + '">' + escapeHtml(kind) + "</option>";
          })
          .join("") +
        "</select>";
    }
    html += '<span class="filter-count" data-filter-count></span></div>';
    return html;
  }

  function attachFilters() {
    var toolbars = document.querySelectorAll(".filter-toolbar");
    for (var index = 0; index < toolbars.length; index += 1) {
      (function (toolbar) {
        var targets = (toolbar.getAttribute("data-filter-targets") || "")
          .split(" ")
          .map(function (id) {
            return document.getElementById(id);
          })
          .filter(Boolean);
        var textInput = toolbar.querySelector("[data-filter-text]");
        var namespaceInput = toolbar.querySelector("[data-filter-namespace]");
        var kindSelect = toolbar.querySelector("[data-filter-kind]");
        var countEl = toolbar.querySelector("[data-filter-count]");

        function apply() {
          var needle = textInput ? textInput.value.trim().toLowerCase() : "";
          var namespace = namespaceInput ? namespaceInput.value.trim() : "";
          var kind = kindSelect ? kindSelect.value : "";
          var shown = 0;
          var total = 0;
          targets.forEach(function (container) {
            var rows = container.querySelectorAll("tbody tr");
            for (var rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
              var row = rows[rowIndex];
              var rowNamespace = row.getAttribute("data-namespace") || "";
              var visible =
                (!needle || (row.getAttribute("data-search") || "").indexOf(needle) !== -1) &&
                namespaceMatches(rowNamespace, namespace) &&
                (!kind || row.getAttribute("data-kind") === kind);
              row.hidden = !visible;
              total += 1;
              if (visible) {
                shown += 1;
              }
            }
          });
          if (countEl) {
            countEl.textContent = shown === total ? total + " row(s)" : shown + " of " + total + " row(s)";
          }
        }

        if (textInput) {
          textInput.addEventListener("input", apply);
        }
        if (namespaceInput) {
          namespaceInput.addEventListener("input", apply);
        }
        if (kindSelect) {
          kindSelect.addEventListener("change", apply);
        }
        apply();
      })(toolbars[index]);
    }
  }

  function definitionList(pairs) {
    var visible = pairs.filter(function (pair) {
      return !isEmpty(pair[1]);
    });
    if (!visible.length) {
      return emptyBlock("Nothing declared.");
    }
    return (
      '<dl class="kv">' +
      visible
        .map(function (pair) {
          return "<dt>" + escapeHtml(pair[0]) + "</dt><dd>" + pair[1] + "</dd>";
        })
        .join("") +
      "</dl>"
    );
  }

  function chips(values, className) {
    if (!values || !values.length) {
      return "";
    }
    return (
      '<div class="chips">' +
      values
        .map(function (value) {
          return (
            '<span class="badge ' +
            (className || "") +
            '">' +
            escapeHtml(value) +
            "</span>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function structureLink(structureId) {
    if (!structureId) {
      return "—";
    }
    if (structureById[structureId]) {
      return (
        '<a href="#/structure/' +
        encodeSegment(structureId) +
        '">' +
        displayId(structureId) +
        "</a>"
      );
    }
    return '<span class="muted">' + displayId(structureId) + "</span>";
  }

  function flowLink(flowId) {
    if (!flowId) {
      return "—";
    }
    if (flowById[flowId]) {
      return (
        '<a href="#/flow/' + encodeSegment(flowId) + '">' + displayId(flowId) + "</a>"
      );
    }
    return '<span class="muted">' + displayId(flowId) + "</span>";
  }

  function entityLinkByName(entityType, name) {
    var candidates = (entitiesByType[entityType] || []).filter(function (entity) {
      return entity.name === name;
    });
    if (!candidates.length) {
      return "<code class='inline'>" + escapeHtml(name) + "</code>";
    }
    return (
      '<a href="#/entity/' +
      encodeSegment(entityType) +
      "/" +
      encodeSegment(candidates[0].node_id) +
      '">' +
      escapeHtml(name) +
      "</a>"
    );
  }

  function namespaceLink(namespace) {
    return (
      '<a href="#/namespace/' +
      encodeSegment(namespace) +
      '">' +
      escapeHtml(namespaceLabel(namespace)) +
      "</a>"
    );
  }

  function documentationBlocks(blocks) {
    if (!blocks || !blocks.length) {
      return "";
    }
    return blocks
      .map(function (block) {
        return card(
          block.title || "Documentation",
          renderMarkdown(block.content) +
            (block.source_path
              ? '<p class="muted" style="margin-bottom:0">' +
                escapeHtml(block.source_path) +
                "</p>"
              : "")
        );
      })
      .join("");
  }

  function jsonBlock(value) {
    return "<pre>" + escapeHtml(JSON.stringify(value, null, 2)) + "</pre>";
  }

  function jsonToggle(value) {
    return "<details><summary>Show JSON</summary>" + jsonBlock(value) + "</details>";
  }

  function isScalar(value) {
    return value === null || value === undefined || typeof value !== "object";
  }

  function isScalarArray(value) {
    return Array.isArray(value) && value.every(isScalar);
  }

  function isRecordArray(value) {
    return (
      Array.isArray(value) &&
      value.length > 0 &&
      value.every(function (item) {
        return item !== null && typeof item === "object" && !Array.isArray(item);
      })
    );
  }

  function formatScalar(value) {
    if (value === null || value === undefined) {
      return "";
    }
    if (typeof value === "boolean") {
      return value ? "yes" : "no";
    }
    return escapeHtml(value);
  }

  function recordsTable(records) {
    if (!records || !records.length) {
      return "";
    }
    var columns = [];
    records.forEach(function (record) {
      Object.keys(record).forEach(function (key) {
        if (columns.indexOf(key) === -1) {
          columns.push(key);
        }
      });
    });
    return table(
      columns,
      records.map(function (record) {
        return columns.map(function (column) {
          return nestedValue(record[column], 1);
        });
      })
    );
  }

  function nestedValue(value, depth) {
    if (isScalar(value)) {
      return formatScalar(value);
    }
    if (isScalarArray(value)) {
      return chips(
        value.map(function (item) {
          return item === null || item === undefined ? "null" : String(item);
        })
      );
    }
    if (depth > 2) {
      return jsonBlock(value);
    }
    if (isRecordArray(value)) {
      return recordsTable(value);
    }
    if (Array.isArray(value)) {
      return jsonBlock(value);
    }
    var keys = Object.keys(value);
    if (!keys.length) {
      return "";
    }
    return (
      '<dl class="kv nested">' +
      keys
        .map(function (key) {
          return "<dt>" + escapeHtml(key) + "</dt><dd>" + nestedValue(value[key], depth + 1) + "</dd>";
        })
        .join("") +
      "</dl>"
    );
  }

  function objectCard(title, value) {
    if (isEmpty(value)) {
      return "";
    }
    var body = Array.isArray(value)
      ? isRecordArray(value)
        ? recordsTable(value)
        : nestedValue(value, 0)
      : definitionList(
          Object.keys(value).map(function (key) {
            return [key, nestedValue(value[key], 1)];
          })
        );
    return card(title, body + jsonToggle(value));
  }

  var SQL_KEYWORDS =
    "select from where and or not in is null as on join left right inner outer full cross " +
    "group by order having limit offset union all distinct case when then else end insert " +
    "into values update set delete merge using create table view replace with recursive " +
    "exists between like ilike cast coalesce nullif over partition window rows range " +
    "asc desc true false interval date timestamp qualify except intersect temp temporary " +
    "if drop alter add column primary key unique index truncate returning lateral unnest " +
    "array struct pivot unpivot any some fetch first next only top";
  var sqlKeywordSet = {};
  SQL_KEYWORDS.split(" ").forEach(function (word) {
    sqlKeywordSet[word] = true;
  });

  function highlightSql(sql) {
    var pattern = /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^'\\]|\\.|'')*')|("(?:[^"\\]|\\.)*"|`[^`]*`)|(\b\d+(?:\.\d+)?\b)|(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\})|([A-Za-z_][A-Za-z0-9_]*)/g;
    var out = "";
    var last = 0;
    var match;
    while ((match = pattern.exec(sql)) !== null) {
      out += escapeHtml(sql.slice(last, match.index));
      var token = match[0];
      var cls = null;
      if (match[1]) {
        cls = "sql-comment";
      } else if (match[2]) {
        cls = "sql-string";
      } else if (match[3]) {
        cls = "sql-identifier";
      } else if (match[4]) {
        cls = "sql-number";
      } else if (match[5]) {
        cls = "sql-template";
      } else if (match[6] && sqlKeywordSet[token.toLowerCase()]) {
        cls = "sql-keyword";
      }
      out += cls ? '<span class="' + cls + '">' + escapeHtml(token) + "</span>" : escapeHtml(token);
      last = match.index + token.length;
    }
    out += escapeHtml(sql.slice(last));
    return '<pre class="sql">' + out + "</pre>";
  }

  function sqlCard(flow) {
    var badge = flow.sql_auto_rendered
      ? ' <span class="badge accent" title="No .sql file next to the flow: the query is rendered from target_from_sources_mapping at run time.">auto-rendered</span>'
      : "";
    var origin = flow.sql_path
      ? '<p class="muted">' + escapeHtml(flow.sql_path) + "</p>"
      : flow.sql_auto_rendered
        ? '<p class="muted">Rendered from the flow metadata; no <code class="inline">' +
          escapeHtml(flow.name + ".sql") +
          "</code> file exists next to the definition.</p>"
        : "";
    var body = "";
    if (flow.sql_rendering_error) {
      body += '<div class="empty error-text">' + escapeHtml(flow.sql_rendering_error) + "</div>";
    }
    if (flow.sql_text) {
      body += highlightSql(flow.sql_text);
    }
    var config = flow.sql || {};
    var configPairs = [
      ["Transformation", formatScalar(config.transformation)],
      ["Rendering", config.no_rendering ? "disabled (no_rendering)" : ""],
      ["Parameters", nestedValue(config.parameters, 1)],
      ["Pre-hooks", hookBlocks(config.pre_hook)],
      ["Post-hooks", hookBlocks(config.post_hook)],
    ].filter(function (pair) {
      return !isEmpty(pair[1]);
    });
    if (configPairs.length) {
      body += "<h3>SQL configuration</h3>" + definitionList(configPairs);
    }
    if (!body) {
      return "";
    }
    return cardWithBadge("SQL", badge, origin + body);
  }

  /* ---------------------------------------------------------------- pages */

  function pageOverview() {
    var project = snapshot.project || {};
    var counts = snapshot.counts || {};
    var coverage = snapshot.documentation_coverage || { documented: 0, total: 0 };
    var coveragePercent =
      coverage.total > 0
        ? Math.round((coverage.documented / coverage.total) * 100)
        : 0;

    var tiles = [
      ["#/structures", counts.structure || 0, "Structures"],
      ["#/flows", counts.flows || 0, "Flows"],
      ["#/namespaces", (snapshot.namespaces || []).length, "Namespaces"],
      ["#/lineage", (snapshot.lineage && snapshot.lineage.nodes.length) || 0, "Lineage nodes"],
      ["#/coverage", coveragePercent + "%", "Documented"],
    ]
      .map(function (tile) {
        return (
          '<a class="tile" href="' +
          tile[0] +
          '"><div class="value">' +
          escapeHtml(tile[1]) +
          '</div><div class="label">' +
          escapeHtml(tile[2]) +
          "</div></a>"
        );
      })
      .join("");

    var connectionRows = (project.connections || []).map(function (connection) {
      return [
        "<code class='inline'>" + escapeHtml(connection.name) + "</code>",
        connection.connector_type
          ? escapeHtml(connection.connector_type)
          : '<span class="muted" title="Not resolved by the local connection configuration">unresolved</span>',
        collapsedList(
          (connection.referenced_by || []).map(function (reference) {
            var flowMatch = /^flow (.+)$/.exec(reference);
            return flowMatch ? "flow " + flowLink(flowMatch[1]) : escapeHtml(reference);
          }),
          4
        ),
      ];
    });
    var brokenIssues = (snapshot.issues || []).filter(function (issue) {
      return issue.kind === "broken_reference";
    });

    var propertyRows = Object.keys(project.properties || {})
      .sort()
      .map(function (key) {
        return [escapeHtml(key), escapeHtml(project.properties[key])];
      });

    return (
      "<h1>" +
      escapeHtml(project.name || "nld project") +
      "</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(
        "Version " +
          (project.version || "—") +
          " · generated " +
          formatDate(snapshot.meta && snapshot.meta.generated_at)
      ) +
      "</p>" +
      '<div class="tile-row">' +
      tiles +
      "</div>" +
      documentationBlocks(project.documentation) +
      card(
        "Project",
        definitionList([
          ["Name", escapeHtml(project.name)],
          ["Version", escapeHtml(project.version)],
          ["Entity path", "<code class='inline'>" + escapeHtml(project.entity_path) + "</code>"],
          ["Default environment", escapeHtml(project.default_environment)],
          ["Environments", chips(project.environments)],
          [
            "Metadata backend",
            project.metadata_backend_connector
              ? "<code class='inline'>" +
                escapeHtml(project.metadata_backend_connector) +
                "</code>"
              : "",
          ],
          ["Snapshot schema", escapeHtml(snapshot.schema_version)],
          [
            "Generator",
            escapeHtml(snapshot.meta && snapshot.meta.generator_version ? "nld-core " + snapshot.meta.generator_version : ""),
          ],
        ])
      ) +
      card("Connections", table(["Name", "Type", "Referenced by"], connectionRows)) +
      (propertyRows.length ? card("Properties", table(["Key", "Value"], propertyRows)) : "") +
      card(
        "Documentation coverage",
        "<p>" +
          escapeHtml(
            coverage.documented +
              " of " +
              coverage.total +
              " documentable assets carry a markdown block (" +
              coveragePercent +
              "%)."
          ) +
          ' <a href="#/coverage">See what is missing</a>.</p>'
      ) +
      (brokenIssues.length
        ? cardWithBadge(
            "Broken references",
            '<span class="badge error">' + brokenIssues.length + "</span>",
            issuesTable(brokenIssues)
          )
        : "")
    );
  }

  function collapsedList(items, visibleCount) {
    if (items.length <= visibleCount + 1) {
      return items.join("<br />");
    }
    return (
      items.slice(0, visibleCount).join("<br />") +
      "<details><summary>" +
      (items.length - visibleCount) +
      " more</summary>" +
      items.slice(visibleCount).join("<br />") +
      "</details>"
    );
  }

  function assetLink(assetId) {
    var separator = assetId.indexOf(":");
    var kind = separator === -1 ? "" : assetId.slice(0, separator);
    var identifier = separator === -1 ? assetId : assetId.slice(separator + 1);
    if (kind === "structure") {
      return structureLink(identifier);
    }
    if (kind === "flow") {
      return flowLink(identifier);
    }
    if (kind && entitiesByType[kind]) {
      return (
        '<a href="#/entity/' + encodeSegment(kind) + "/" + encodeSegment(identifier) + '">' +
        displayId(identifier) +
        "</a>"
      );
    }
    return "<code class='inline'>" + escapeHtml(assetId) + "</code>";
  }

  function assetKind(assetId) {
    var separator = assetId.indexOf(":");
    return separator === -1 ? "asset" : assetId.slice(0, separator);
  }

  function issuesTable(issues) {
    return table(
      ["Kind", "Asset", "Detail"],
      issues.map(function (issue) {
        return [
          '<span class="badge ' + (issue.kind === "broken_reference" ? "error" : "") + '">' +
            escapeHtml(issue.kind.replace(/_/g, " ")) +
            "</span>",
          assetLink(issue.asset),
          escapeHtml(issue.message),
        ];
      })
    );
  }

  function pageCoverage() {
    var coverage = snapshot.documentation_coverage || { documented: 0, total: 0, missing: [] };
    var coveragePercent =
      coverage.total > 0 ? Math.round((coverage.documented / coverage.total) * 100) : 0;
    var missing = coverage.missing || [];
    var issues = snapshot.issues || [];
    return (
      "<h1>Documentation coverage</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(
        coverage.documented +
          " of " +
          coverage.total +
          " documentable asset(s) documented (" +
          coveragePercent +
          "%). A structure counts as documented with a description or a markdown sidecar; a flow needs a sidecar."
      ) +
      "</p>" +
      filterToolbar(["coverage-table"], {
        placeholder: "Filter undocumented assets…",
        namespaces: namespaceOptions(
          missing.map(function (assetId) {
            return splitId(assetId.slice(assetId.indexOf(":") + 1)).namespace;
          })
        ),
        kinds: namespaceOptions(missing.map(assetKind)).filter(function (kind) {
          return kind !== ".";
        }),
      }) +
      card(
        "Undocumented assets (" + missing.length + ")",
        '<div id="coverage-table">' +
          (missing.length
            ? tableWithMeta(
                ["Kind", "Asset"],
                missing.map(function (assetId) {
                  var identifier = assetId.slice(assetId.indexOf(":") + 1);
                  return {
                    name: splitId(identifier).name,
                    namespace: splitId(identifier).namespace,
                    kind: assetKind(assetId),
                    search: identifier,
                    cells: [escapeHtml(assetKind(assetId)), assetLink(assetId)],
                  };
                })
              )
            : emptyBlock("Every documentable asset is documented.")) +
          "</div>"
      ) +
      card(
        "Repository issues (" + issues.length + ")",
        issues.length
          ? issuesTable(issues) +
              '<p class="muted" style="margin-bottom:0">Broken references make <code class="inline">nld docs check</code> fail; unused templates are informational.</p>'
          : emptyBlock("No broken reference and no unused template.")
      )
    );
  }

  function pageStructures() {
    var structures = snapshot.structures || [];
    var rows = structures.map(function (structure) {
      var description = structure.short_description || structure.description || "";
      return {
        name: structure.name,
        namespace: structure.namespace,
        search: [structure.node_id, description, (structure.tags || []).join(" ")].join(" "),
        cells: [
          '<a href="#/structure/' +
            encodeSegment(structure.node_id) +
            '">' +
            displayId(structure.node_id) +
            "</a>",
          namespaceLink(structure.namespace),
          escapeHtml(structure.structure_type),
          String((structure.fields || []).length),
          escapeHtml((structure.primary_key_fields || []).join(", ") || "—"),
          chips(structure.tags),
          escapeHtml(description),
        ],
      };
    });
    return (
      "<h1>Structures</h1>" +
      '<p class="page-subtitle">' +
      structures.length +
      " structure(s) declared in this project.</p>" +
      filterToolbar(["structure-table"], {
        placeholder: "Filter structures by name, tag or description…",
        namespaces: namespaceOptions(
          structures.map(function (structure) {
            return structure.namespace;
          })
        ),
      }) +
      card(
        null,
        '<div id="structure-table">' +
          tableWithMeta(
            ["Name", "Namespace", "Type", "Fields", "Primary key", "Tags", "Description"],
            rows
          ) +
          "</div>"
      )
    );
  }

  function fieldOrigin(field) {
    if (field.declared === false) {
      return field.from_structure_template
        ? '<span class="badge">structure template</span> ' +
            entityLinkByName("structure_template", field.from_structure_template)
        : '<span class="badge">template</span>';
    }
    return '<span class="muted">declared</span>';
  }

  function fieldRows(fields, depth) {
    var rows = [];
    (fields || []).forEach(function (field) {
      var indent = depth > 0 ? ' class="nested-field"' : "";
      var description = field.description || field.short_description || "";
      rows.push({
        name: field.name,
        namespace: null,
        search: [field.data_type, description, (field.characterisations || []).join(" "), field.from_template || ""].join(" "),
        cells: [
          "<span" +
            indent +
            ' id="field-' +
            escapeHtml(field.name) +
            '">' +
            escapeHtml(field.name) +
            "</span>",
          escapeHtml(
            field.data_type +
              (field.length ? "(" + field.length + (field.precision ? "," + field.precision : "") + ")" : "")
          ),
          chips(field.characterisations, "accent"),
          field.from_template ? entityLinkByName("field_template", field.from_template) : "",
          depth > 0 ? "" : fieldOrigin(field),
          escapeHtml(field.default_value === null || field.default_value === undefined ? "" : field.default_value),
          escapeHtml(description),
        ],
      });
      rows = rows.concat(fieldRows(field.fields, depth + 1));
    });
    return rows;
  }

  function pageStructure(structureId) {
    var structure = structureById[structureId];
    if (!structure) {
      return notFound("structure", structureId);
    }

    var characterisationRows = (structure.characterisations || []).map(function (item) {
      return [
        escapeHtml(item.characterisation),
        escapeHtml(item.name || ""),
        escapeHtml((item.linked_fields || []).join(", ")),
      ];
    });

    var linkRows = (structure.model_links || []).map(function (link) {
      return [
        escapeHtml(link.link || ""),
        structureLink(link.left_structure),
        structureLink(link.right_structure),
        escapeHtml(link.cardinality || ""),
        escapeHtml(
          (link.left_to_right_mappings || [])
            .map(function (mapping) {
              return mapping.left + " → " + mapping.right;
            })
            .join(", ")
        ),
      ];
    });

    return (
      '<div class="breadcrumb"><a href="#/structures">Structures</a> / ' +
      namespaceLink(structure.namespace) +
      "</div>" +
      "<h1>" +
      displayId(structure.node_id) +
      "</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(structure.description || structure.short_description || "No description.") +
      "</p>" +
      documentationBlocks(structure.documentation) +
      card(
        "Definition",
        definitionList([
          ["Identifier", "<code class='inline'>" + escapeHtml(structure.node_id) + "</code>"],
          ["Namespace", namespaceLink(structure.namespace)],
          ["Type", escapeHtml(structure.structure_type)],
          ["Connector type", escapeHtml(structure.connector_type)],
          ["Short name", escapeHtml(structure.short_name)],
          ["Primary key", escapeHtml((structure.primary_key_fields || []).join(", "))],
          ["Tags", chips(structure.tags)],
          ["Templates", chips(structure.templates, "accent")],
          [
            "Source file",
            structure.source_path
              ? "<code class='inline'>" + escapeHtml(structure.source_path) + "</code>"
              : "",
          ],
        ])
      ) +
      card(
        "Fields (" + (structure.fields || []).length + ")",
        fieldsNote(structure.fields) +
          filterToolbar(["fields-table"], {
            placeholder: "Filter fields by name, type, characterisation or description…",
          }) +
          '<div id="fields-table">' +
          tableWithMeta(
            ["Field", "Type", "Characterisations", "Template", "Origin", "Default", "Description"],
            fieldRows(structure.fields, 0)
          ) +
          "</div>"
      ) +
      (characterisationRows.length
        ? card(
            "Structure characterisations",
            table(["Characterisation", "Name", "Fields"], characterisationRows)
          )
        : "") +
      card(
        "Lineage",
        definitionList([
          [
            "Produced by",
            (structure.produced_by || []).map(flowLink).join("<br />"),
          ],
          [
            "Consumed by",
            (structure.consumed_by || []).map(flowLink).join("<br />"),
          ],
          ["Graph", lineageLink("structure", structure.node_id)],
        ])
      ) +
      (linkRows.length
        ? card(
            "Model links",
            table(["Link", "Left", "Right", "Cardinality", "Mappings"], linkRows)
          )
        : "") +
      card(
        "Governance",
        definitionList([
          ["Data owners", ownerList(structure.data_owners)],
          ["Technical owners", ownerList(structure.technical_owners)],
          ["Properties", keyValueChips(structure.properties)],
          ["Business metadata", keyValueChips(structure.business_metadata)],
        ])
      ) +
      deploymentCard(structure) +
      auditCardFor(structure) +
      sourceCard(structure)
    );
  }

  function fieldsNote(fields) {
    var fromTemplates = (fields || []).filter(function (field) {
      return field.declared === false;
    }).length;
    if (!fromTemplates) {
      return "";
    }
    return (
      '<p class="muted">The physical table as deployed: ' +
      ((fields || []).length - fromTemplates) +
      " declared field(s) and " +
      fromTemplates +
      " field(s) contributed by structure templates, in deployment order.</p>"
    );
  }

  function lineageKey(nodeType, nodeId) {
    return nodeType + ":" + nodeId;
  }

  function lineageLink(nodeType, nodeId) {
    return (
      '<a href="#/lineage/' +
      encodeSegment(lineageKey(nodeType, nodeId)) +
      '">View in lineage</a>'
    );
  }

  function hookBlocks(statements) {
    if (!statements || !statements.length) {
      return "";
    }
    return (
      '<div class="sql-hooks">' +
      statements
        .map(function (statement) {
          return "<pre>" + escapeHtml(statement) + "</pre>";
        })
        .join("") +
      "</div>"
    );
  }

  function valueBlock(value) {
    if (isEmpty(value)) {
      return "";
    }
    if (typeof value !== "object") {
      return escapeHtml(value);
    }
    var scalar = Object.keys(value).every(function (key) {
      return value[key] === null || typeof value[key] !== "object";
    });
    return scalar && !Array.isArray(value) ? keyValueChips(value) : jsonBlock(value);
  }

  function deploymentCard(structure) {
    var pairs = [
      ["Options", valueBlock(structure.options)],
      [
        "Enforce field order",
        structure.enforce_field_order === null || structure.enforce_field_order === undefined
          ? ""
          : structure.enforce_field_order
            ? "yes"
            : "no",
      ],
      ["Pre-deployment SQL hooks", hookBlocks(structure.pre_deployment_sql_hooks)],
      ["Post-deployment SQL hooks", hookBlocks(structure.post_deployment_sql_hooks)],
      ["Origin", valueBlock(structure.origin)],
      ["Stats", valueBlock(structure.stats)],
    ];
    var declared = pairs.filter(function (pair) {
      return !isEmpty(pair[1]);
    });
    if (!declared.length) {
      return "";
    }
    return card("Deployment", definitionList(pairs));
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === "") {
      return "";
    }
    if (typeof value === "number") {
      return Number.isInteger(value) ? value.toLocaleString("en-US") : String(value);
    }
    return String(value);
  }

  function formatPercent(value) {
    if (value === null || value === undefined) {
      return "";
    }
    return Number(value).toFixed(1) + "%";
  }

  function distributionBlock(distribution) {
    if (!distribution || !distribution.values || !distribution.values.length) {
      return "";
    }
    return (
      '<details class="distribution"><summary>top ' +
      distribution.values.length +
      (distribution.truncated ? " (truncated)" : "") +
      "</summary>" +
      table(
        ["Value", "Count", "%"],
        distribution.values.map(function (item) {
          return [
            escapeHtml(item.value === null || item.value === undefined ? "NULL" : item.value),
            formatNumber(item.count),
            formatPercent(item.pct),
          ];
        })
      ) +
      "</details>"
    );
  }

  function auditCardFor(structure) {
    if (!structure.audit_id) {
      return "";
    }
    var audits = entitiesByType.structure_audit || [];
    var entity = audits.filter(function (item) {
      return item.node_id === structure.audit_id;
    })[0];
    if (!entity) {
      return "";
    }
    return auditCard(entity.payload || {}, entity);
  }

  function auditCard(audit, entity) {
    var target = audit.target || {};
    var metadata = audit.metadata || {};
    var sampling = metadata.sampling || {};
    var dateCoverage = metadata.date_coverage || null;
    var columns = audit.columns || {};
    var columnRows = Object.keys(columns).map(function (key) {
      var column = columns[key] || {};
      var coverage = column.coverage || {};
      return [
        escapeHtml(column.name || key),
        escapeHtml(column.data_type || ""),
        column.nullable === null || column.nullable === undefined
          ? ""
          : column.nullable
            ? "yes"
            : "no",
        column.primary_key ? '<span class="badge accent">PK</span>' : "",
        formatNumber(coverage.non_null),
        formatPercent(coverage.pct),
        formatNumber(coverage.distinct),
        escapeHtml(coverage.min === null || coverage.min === undefined ? "" : coverage.min),
        escapeHtml(coverage.max === null || coverage.max === undefined ? "" : coverage.max),
        distributionBlock(column.distribution),
        escapeHtml(column.notes || ""),
      ];
    });
    var samplingText = sampling.sampled
      ? "sampled" +
        (sampling.method ? " · " + sampling.method : "") +
        (sampling.sample_size ? " · " + formatNumber(sampling.sample_size) + " rows" : "") +
        (sampling.fraction ? " · " + formatPercent(sampling.fraction * 100) : "")
      : "full scan";
    return card(
      "Latest audit" + (audit.name ? " — " + audit.name : ""),
      (entity
        ? '<p class="muted"><a href="#/entity/structure_audit/' +
          encodeSegment(entity.node_id) +
          '">Open the audit entity</a>' +
          (entity.source_path ? " · " + escapeHtml(entity.source_path) : "") +
          "</p>"
        : "") +
        (audit.description ? "<p>" + escapeHtml(audit.description) + "</p>" : "") +
        definitionList([
          ["Environment", escapeHtml(target.environment)],
          ["Connection", escapeHtml(target.connection)],
          ["Connector type", escapeHtml(target.connector_type)],
          ["Database", escapeHtml(target.database)],
          ["Schema", escapeHtml(target.schema)],
          ["Audited at", escapeHtml(metadata.audited_at)],
          ["Row count", formatNumber(metadata.row_count)],
          ["Sampling", escapeHtml(samplingText)],
          [
            "Date coverage",
            dateCoverage
              ? escapeHtml(
                  (dateCoverage.field_characterisation || "") +
                    " " +
                    (dateCoverage.from || "?") +
                    " → " +
                    (dateCoverage.to || "?")
                )
              : "",
          ],
        ]) +
        "<h3>Columns (" + columnRows.length + ")</h3>" +
        '<div class="audit-columns">' +
        table(
          [
            "Column",
            "Type",
            "Nullable",
            "Key",
            "Non-null",
            "Coverage",
            "Distinct",
            "Min",
            "Max",
            "Distribution",
            "Notes",
          ],
          columnRows
        ) +
        "</div>" +
        jsonToggle(audit)
    );
  }

  function ownerList(owners) {
    if (!owners || !owners.length) {
      return "";
    }
    return owners
      .map(function (owner) {
        return (
          escapeHtml(owner.team) +
          (owner.contact ? " &lt;" + escapeHtml(owner.contact) + "&gt;" : "") +
          ' <span class="muted">(' +
          escapeHtml(namespaceLabel(owner.source_namespace)) +
          (owner.via ? ", " + escapeHtml(owner.via) : "") +
          ")</span>"
        );
      })
      .join("<br />");
  }

  function keyValueChips(mapping) {
    var keys = Object.keys(mapping || {});
    if (!keys.length) {
      return "";
    }
    return chips(
      keys.sort().map(function (key) {
        return key + ": " + mapping[key];
      })
    );
  }

  function sourceCard(entity) {
    if (!entity.source_text) {
      return "";
    }
    return card(
      "Source" + (entity.source_path ? " — " + entity.source_path : ""),
      "<pre>" + escapeHtml(entity.source_text) + "</pre>"
    );
  }

  function pageFlows() {
    var flows = snapshot.flows || [];
    var rows = flows.map(function (flow) {
      return {
        name: flow.name,
        namespace: flow.namespace,
        search: [flow.node_id, flow.target_structure || "", flow.description || ""].join(" "),
        cells: [
          '<a href="#/flow/' + encodeSegment(flow.node_id) + '">' + displayId(flow.node_id) + "</a>",
          namespaceLink(flow.namespace),
          structureLink(flow.target_structure),
          escapeHtml(flow.write_strategy || "—"),
          String((flow.predecessors || []).length),
          escapeHtml(
            flow.incremental && flow.incremental.type ? flow.incremental.type : "—"
          ),
          chips(
            (flow.schedules || []).map(function (schedule) {
              return schedule.environment + ": " + (schedule.trigger_kind || "—");
            })
          ),
          escapeHtml(flow.description || ""),
        ],
      };
    });
    return (
      "<h1>Flows</h1>" +
      '<p class="page-subtitle">' +
      flows.length +
      " flow(s) declared in this project.</p>" +
      filterToolbar(["flow-table"], {
        placeholder: "Filter flows by name, target or description…",
        namespaces: namespaceOptions(
          flows.map(function (flow) {
            return flow.namespace;
          })
        ),
      }) +
      card(
        null,
        '<div id="flow-table">' +
          tableWithMeta(
            ["Name", "Namespace", "Target", "Strategy", "Sources", "Incremental", "Scheduling", "Description"],
            rows
          ) +
          "</div>"
      )
    );
  }

  function pageFlow(flowId) {
    var flow = flowById[flowId];
    if (!flow) {
      return notFound("flow", flowId);
    }

    var predecessorRows = (flow.predecessors || []).map(function (predecessor) {
      return [
        escapeHtml(predecessor.name),
        structureLink(predecessor.full_path),
        escapeHtml(predecessor.role || ""),
        escapeHtml(predecessor.key_field || ""),
      ];
    });

    var scheduleRows = (flow.schedules || []).map(function (schedule) {
      return [
        escapeHtml(schedule.environment),
        schedule.enabled ? '<span class="badge ok">enabled</span>' : '<span class="badge">disabled</span>',
        escapeHtml(schedule.trigger_kind || "—"),
        schedule.cron ? "<code class='inline'>" + escapeHtml(schedule.cron) + "</code>" : "—",
        escapeHtml((schedule.predecessors || []).join(", ") || "—"),
        resolvedPredecessors(schedule),
        escapeHtml(schedule.frequency ? schedule.frequency.value : "—"),
        schedule.max_attempts
          ? '<span title="' +
            escapeHtml(schedule.max_attempts_origin || "") +
            '">' +
            escapeHtml(schedule.max_attempts) +
            "</span>"
          : "—",
        keyValueChips(schedule.params) || "—",
      ];
    });

    var lineageRows = Object.keys(flow.field_lineage || {})
      .sort()
      .map(function (target) {
        var lineage = flow.field_lineage[target];
        var origin =
          typeof lineage === "string"
            ? lineage
            : (lineage && (lineage.origin || lineage.expression)) ||
              JSON.stringify(lineage);
        return [escapeHtml(target), "<code class='inline'>" + escapeHtml(origin) + "</code>"];
      });

    return (
      '<div class="breadcrumb"><a href="#/flows">Flows</a> / ' +
      namespaceLink(flow.namespace) +
      "</div>" +
      "<h1>" +
      displayId(flow.node_id) +
      "</h1>" +
      '<p class="page-subtitle">' +
      (flow.description ? escapeHtml(flow.description) : displayId(flow.node_id)) +
      "</p>" +
      documentationBlocks(flow.documentation) +
      card(
        "Definition",
        definitionList([
          ["Target structure", structureLink(flow.target_structure)],
          ["Write strategy", escapeHtml(flow.write_strategy)],
          ["Task", flow.task ? "<code class='inline'>" + escapeHtml(flow.task) + "</code>" : ""],
          ["Task type", escapeHtml(flow.task_type)],
          ["Owner", ownerList(flow.owner ? [flow.owner] : [])],
          ["Graph", lineageLink("flow", flow.node_id)],
          [
            "Source file",
            flow.source_path
              ? "<code class='inline'>" + escapeHtml(flow.source_path) + "</code>"
              : "",
          ],
        ])
      ) +
      card("Sources", table(["Name", "Structure", "Role", "Key field"], predecessorRows)) +
      objectCard("Incremental", flow.incremental) +
      sqlCard(flow) +
      (lineageRows.length
        ? card("Field lineage", table(["Target field", "Origin"], lineageRows))
        : "") +
      objectCard("Quality checks", flow.quality_checks) +
      (scheduleRows.length
        ? card(
            "Scheduling",
            table(
              [
                "Environment",
                "State",
                "Trigger",
                "Cron",
                "Declared predecessors",
                "Resolved predecessors",
                "Frequency",
                "Retries",
                "Params",
              ],
              scheduleRows
            ) +
              '<p class="muted" style="margin-bottom:0">Resolved predecessors are the tasks the scheduler waits for once the automatic lineage and the declared adjustments are applied. Retries count the first attempt; hover the value for the declaration that set it.</p>'
          )
        : "") +
      ((flow.params || []).length ? card("Parameters", recordsTable(flow.params)) : "") +
      ((flow.variables || []).length ? card("Variables", recordsTable(flow.variables)) : "") +
      sourceCard(flow)
    );
  }

  function resolvedPredecessors(schedule) {
    if (schedule.resolution_error) {
      return (
        '<span class="badge error" title="' +
        escapeHtml(schedule.resolution_error) +
        '">unresolved</span>'
      );
    }
    var items = schedule.resolved_predecessors || [];
    if (!items.length) {
      return "—";
    }
    return items
      .map(function (item) {
        if (item.external) {
          return displayId(item.task_id) + ' <span class="badge">external</span>';
        }
        return item.flow_id ? flowLink(item.flow_id) : displayId(item.task_id);
      })
      .join("<br />");
  }

  function pageNamespaces() {
    var namespaces = snapshot.namespaces || [];
    var rows = namespaces.map(function (namespace) {
      var counts = namespace.entity_counts || {};
      var total = Object.keys(counts).reduce(function (sum, key) {
        return sum + counts[key];
      }, 0);
      return {
        name: namespaceLabel(namespace.namespace),
        namespace: namespace.namespace,
        search: (namespace.documentation || [])
          .map(function (block) {
            return block.content;
          })
          .join(" "),
        cells: [
          namespaceLink(namespace.namespace),
          String(total),
          chips(
            Object.keys(counts)
              .sort()
              .map(function (key) {
                return key + ": " + counts[key];
              })
          ),
          namespace.documentation && namespace.documentation.length
            ? '<span class="badge ok">documented</span>'
            : "",
        ],
      };
    });
    return (
      "<h1>Namespaces</h1>" +
      '<p class="page-subtitle">' +
      namespaces.length +
      " namespace(s) hold the assets of this project.</p>" +
      filterToolbar(["namespace-table"], { placeholder: "Filter namespaces…" }) +
      card(
        null,
        '<div id="namespace-table">' +
          tableWithMeta(["Namespace", "Assets", "Breakdown", "Docs"], rows) +
          "</div>"
      )
    );
  }

  function pageNamespace(namespace) {
    var summary = namespaceByName[namespace];
    var structures = (snapshot.structures || []).filter(function (structure) {
      return structure.namespace === namespace;
    });
    var flows = (snapshot.flows || []).filter(function (flow) {
      return flow.namespace === namespace;
    });

    return (
      '<div class="breadcrumb"><a href="#/namespaces">Namespaces</a></div>' +
      "<h1>" +
      escapeHtml(namespaceLabel(namespace)) +
      "</h1>" +
      (summary ? documentationBlocks(summary.documentation) : "") +
      filterToolbar(["ns-structures", "ns-flows", "ns-others"], {
        placeholder: "Filter the assets of this namespace…",
      }) +
      card(
        "Structures (" + structures.length + ")",
        '<div id="ns-structures">' +
          tableWithMeta(
            ["Name", "Type", "Fields", "Description"],
            structures.map(function (structure) {
              var description = structure.short_description || structure.description || "";
              return {
                name: structure.name,
                namespace: structure.namespace,
                search: description,
                cells: [
                  '<a href="#/structure/' +
                    encodeSegment(structure.node_id) +
                    '">' +
                    escapeHtml(structure.name) +
                    "</a>",
                  escapeHtml(structure.structure_type),
                  String((structure.fields || []).length),
                  escapeHtml(description),
                ],
              };
            })
          ) +
          "</div>"
      ) +
      card(
        "Flows (" + flows.length + ")",
        '<div id="ns-flows">' +
          tableWithMeta(
            ["Name", "Target", "Strategy", "Description"],
            flows.map(function (flow) {
              return {
                name: flow.name,
                namespace: flow.namespace,
                search: [flow.target_structure || "", flow.description || ""].join(" "),
                cells: [
                  '<a href="#/flow/' + encodeSegment(flow.node_id) + '">' + escapeHtml(flow.name) + "</a>",
                  structureLink(flow.target_structure),
                  escapeHtml(flow.write_strategy || "—"),
                  escapeHtml(flow.description || ""),
                ],
              };
            })
          ) +
          "</div>"
      ) +
      card(
        "Other assets",
        '<div id="ns-others">' +
          tableWithMeta(
            ["Entity type", "Name", "Description"],
            Object.keys(entitiesByType)
              .sort()
              .reduce(function (rows, entityType) {
                (entitiesByType[entityType] || []).forEach(function (entity) {
                  if (entity.namespace !== namespace) {
                    return;
                  }
                  rows.push({
                    name: entity.name,
                    namespace: entity.namespace,
                    kind: entityType,
                    search: [entity.display_name, entity.description || ""].join(" "),
                    cells: [
                      escapeHtml(entity.display_name),
                      '<a href="#/entity/' +
                        encodeSegment(entityType) +
                        "/" +
                        encodeSegment(entity.node_id) +
                        '">' +
                        escapeHtml(entity.name) +
                        "</a>",
                      escapeHtml(entity.description || ""),
                    ],
                  });
                });
                return rows;
              }, [])
          ) +
          "</div>"
      )
    );
  }

  function pageEntities(entityType) {
    var entities = entitiesByType[entityType] || [];
    var definition = (snapshot.entity_types || []).filter(function (item) {
      return item.name === entityType;
    })[0];
    var hasUsages = entities.some(function (entity) {
      return (entity.used_by || []).length > 0;
    });
    var rows = entities.map(function (entity) {
      var cells = [
        '<a href="#/entity/' +
          encodeSegment(entityType) +
          "/" +
          encodeSegment(entity.node_id) +
          '">' +
          displayId(entity.node_id) +
          "</a>",
        namespaceLink(entity.namespace),
        escapeHtml(entity.description || ""),
        entity.source_path
          ? "<code class='inline'>" + escapeHtml(entity.source_path) + "</code>"
          : "",
      ];
      if (hasUsages) {
        cells.push(usageCount(entity));
      }
      return {
        name: entity.name,
        namespace: entity.namespace,
        search: [entity.node_id, entity.description || ""].join(" "),
        cells: cells,
      };
    });
    var headers = ["Name", "Namespace", "Description", "Source"];
    if (hasUsages) {
      headers.push("Used by");
    }
    return (
      "<h1>" +
      escapeHtml(definition ? definition.display_name : entityType) +
      "</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(
        entities.length +
          " asset(s)" +
          (definition
            ? " · folder " + definition.folder_name + " · resolved towards " + definition.search_direction
            : "")
      ) +
      "</p>" +
      filterToolbar(["entity-table"], {
        namespaces: namespaceOptions(
          entities.map(function (entity) {
            return entity.namespace;
          })
        ),
      }) +
      card(null, '<div id="entity-table">' + tableWithMeta(headers, rows) + "</div>")
    );
  }

  function usageCount(entity) {
    var usages = entity.used_by || [];
    if (!usages.length) {
      return '<span class="muted">—</span>';
    }
    var structures = {};
    usages.forEach(function (usage) {
      structures[usage.structure_id] = true;
    });
    return (
      Object.keys(structures).length +
      " structure(s)" +
      (usages.some(function (usage) {
        return usage.field_name;
      })
        ? ", " + usages.length + " field(s)"
        : "")
    );
  }

  function usageCard(entity) {
    var usages = entity.used_by || [];
    if (!usages.length) {
      return "";
    }
    return card(
      "Used by (" + usageCount(entity) + ")",
      table(
        ["Structure", "Field", "Via"],
        usages.map(function (usage) {
          return [
            structureLink(usage.structure_id),
            usage.field_name
              ? '<a href="#/structure/' +
                encodeSegment(usage.structure_id) +
                "/field/" +
                encodeSegment(usage.field_name) +
                '">' +
                escapeHtml(usage.field_name) +
                "</a>"
              : "",
            escapeHtml(usage.via || "declared on the structure"),
          ];
        })
      )
    );
  }

  function termsCard(dictionaryNodeId) {
    var terms = termsByDictionary[dictionaryNodeId] || [];
    if (!terms.length) {
      return "";
    }
    return card(
      "Terms (" + terms.length + ")",
      filterToolbar(["terms-table"], { placeholder: "Filter terms, synonyms and translations…" }) +
        '<div id="terms-table">' +
        tableWithMeta(
          ["Term", "Plural", "Description", "Synonyms", "Translations", "Related"],
          terms.map(function (term) {
            var translationNames = (term.translations || []).map(function (translation) {
              return [translation.name].concat(translation.synonyms || []).join(" ");
            });
            return {
              name: term.name,
              namespace: null,
              search: [term.plural || "", term.description || ""]
                .concat(term.synonyms || [])
                .concat(translationNames)
                .join(" "),
              cells: [
                '<strong class="term-anchor" id="term-' +
                  escapeHtml(term.name) +
                  '">' +
                  escapeHtml(term.name) +
                  "</strong>",
                escapeHtml(term.plural || ""),
                escapeHtml(term.description || ""),
                chips(term.synonyms),
                (term.translations || [])
                  .map(function (translation) {
                    return (
                      '<span class="badge accent">' +
                      escapeHtml(translation.language) +
                      "</span> " +
                      escapeHtml(translation.name) +
                      (translation.synonyms && translation.synonyms.length
                        ? ' <span class="muted">(' +
                          escapeHtml(translation.synonyms.join(", ")) +
                          ")</span>"
                        : "")
                    );
                  })
                  .join("<br />"),
                chips(term.related_terms),
              ],
            };
          })
        ) +
        "</div>"
    );
  }

  function pageEntity(entityType, nodeId) {
    var entities = entitiesByType[entityType] || [];
    var entity = entities.filter(function (item) {
      return item.node_id === nodeId;
    })[0];
    if (!entity) {
      return notFound(entityType, nodeId);
    }
    return (
      '<div class="breadcrumb"><a href="#/entities/' +
      encodeSegment(entityType) +
      '">' +
      escapeHtml(entity.display_name) +
      "</a></div>" +
      "<h1>" +
      displayId(entity.node_id) +
      "</h1>" +
      '<p class="page-subtitle">' +
      (entity.description ? escapeHtml(entity.description) : displayId(entity.node_id)) +
      "</p>" +
      documentationBlocks(entity.documentation) +
      card(
        "Definition",
        definitionList([
          ["Entity type", escapeHtml(entity.entity_type)],
          ["Namespace", namespaceLink(entity.namespace)],
          ["Category", escapeHtml(entity.category)],
          [
            "Source file",
            entity.source_path
              ? "<code class='inline'>" + escapeHtml(entity.source_path) + "</code>"
              : "",
          ],
        ])
      ) +
      (entityType === "business_dictionary" ? termsCard(entity.node_id) : "") +
      usageCard(entity) +
      (entityType === "structure_audit" ? auditCard(entity.payload || {}, null) : "") +
      card("Resolved payload", jsonToggle(entity.payload)) +
      sourceCard(entity)
    );
  }

  /* Every reachable node with the number of hops it took to get there, so
     the view can be bounded to "two hops upstream" instead of dragging in
     the whole ancestry of a consumer table. */
  function lineageNeighbourhood(lineage, focusId) {
    var upstream = {};
    var downstream = {};
    lineage.edges.forEach(function (edge) {
      (upstream[edge.target] = upstream[edge.target] || []).push(edge.source);
      (downstream[edge.source] = downstream[edge.source] || []).push(edge.target);
    });
    function walk(start, links) {
      var distances = {};
      var queue = [{ key: start, distance: 0 }];
      while (queue.length) {
        var current = queue.shift();
        (links[current.key] || []).forEach(function (next) {
          if (distances[next] !== undefined || next === start) {
            return;
          }
          distances[next] = current.distance + 1;
          queue.push({ key: next, distance: current.distance + 1 });
        });
      }
      return distances;
    }
    return {
      ancestors: walk(focusId, upstream),
      descendants: walk(focusId, downstream),
      directUpstream: upstream[focusId] || [],
      directDownstream: downstream[focusId] || [],
    };
  }

  /* A node is in view when the direction allows its side and it is within
     the hop budget; a depth of 0 means "no budget". */
  function withinFocus(neighbourhood, focusKey, nodeKey) {
    if (nodeKey === focusKey) {
      return true;
    }
    var depth = lineageOptions.depth;
    var direction = lineageOptions.direction;
    var up = neighbourhood.ancestors[nodeKey];
    if (up !== undefined && direction !== "down" && (!depth || up <= depth)) {
      return true;
    }
    var down = neighbourhood.descendants[nodeKey];
    if (down !== undefined && direction !== "up" && (!depth || down <= depth)) {
      return true;
    }
    return false;
  }

  function lineageNodeLink(node) {
    return node.node_type === "flow" ? flowLink(node.node_id) : structureLink(node.node_id);
  }

  function namespaceHue(namespace) {
    var hash = 0;
    var value = String(namespace || ".");
    for (var index = 0; index < value.length; index += 1) {
      hash = (hash * 31 + value.charCodeAt(index)) % 360;
    }
    return hash;
  }

  function selectOption(value, current, label) {
    return (
      '<option value="' +
      escapeHtml(value) +
      '"' +
      (String(current) === String(value) ? " selected" : "") +
      ">" +
      escapeHtml(label) +
      "</option>"
    );
  }

  function lineageToolbar(allNamespaces, focus, groupCount, error) {
    var isolateAvailable = Boolean(focus);
    return (
      '<div class="lineage-toolbar">' +
      (focus ? '<a href="#/lineage"><button type="button">Clear focus</button></a>' : "") +
      '<input type="search" class="lineage-selection" data-lineage-selection value="' +
      escapeHtml(lineageOptions.selection) +
      '" placeholder="Selection, e.g. 2+namespace:&quot;staging&quot;+1" ' +
      'autocomplete="off" spellcheck="false" />' +
      namespacePicker(
        "data-lineage-namespace",
        allNamespaces,
        selectionNamespacePrefix(lineageOptions.selection),
        "Namespace\u2026"
      ) +
      '<label>Group <select data-lineage-group-depth>' +
      selectOption("1", lineageOptions.groupDepth, "level 1") +
      selectOption("2", lineageOptions.groupDepth, "level 2") +
      selectOption("3", lineageOptions.groupDepth, "level 3") +
      selectOption("0", lineageOptions.groupDepth, "leaf") +
      "</select></label>" +
      (groupCount > 1
        ? '<button type="button" data-lineage-groups="expand">Expand all</button>' +
          '<button type="button" data-lineage-groups="collapse">Collapse all</button>'
        : "") +
      "<label" +
      (isolateAvailable ? "" : ' class="disabled"') +
      ' title="' +
      escapeHtml(
        isolateAvailable
          ? "Which way to follow the lineage of the focused node: what feeds "
            + "it (upstream), what it feeds (downstream), or both"
          : "Select a node to focus on first"
      ) +
      '">Follow <select data-lineage-direction' +
      (isolateAvailable ? "" : " disabled") +
      ">" +
      selectOption("both", lineageOptions.direction, "both ways") +
      selectOption("up", lineageOptions.direction, "upstream") +
      selectOption("down", lineageOptions.direction, "downstream") +
      "</select></label>" +
      "<label" +
      (isolateAvailable ? "" : ' class="disabled"') +
      ' title="' +
      escapeHtml(
        isolateAvailable
          ? "How many hops away from the focused node to follow, so a wide "
            + "graph can be cut to its immediate neighbourhood"
          : "Select a node to focus on first"
      ) +
      '">Hops <select data-lineage-depth' +
      (isolateAvailable ? "" : " disabled") +
      ">" +
      selectOption("0", lineageOptions.depth, "all") +
      selectOption("1", lineageOptions.depth, "1") +
      selectOption("2", lineageOptions.depth, "2") +
      selectOption("3", lineageOptions.depth, "3") +
      "</select></label>" +
      "<label" +
      (isolateAvailable
        ? ""
        : ' class="disabled" title="Select a node to focus on first"') +
      '><input type="checkbox" data-lineage-isolate' +
      (lineageOptions.isolate ? " checked" : "") +
      (isolateAvailable ? "" : " disabled") +
      " /> Only the focused lineage</label>" +
      '<label><input type="checkbox" data-lineage-structures-only' +
      (lineageOptions.structuresOnly ? " checked" : "") +
      " /> Structures only</label>" +
      (error
        ? '<span class="lineage-error">' + escapeHtml(error) + "</span>"
        : '<span class="hint">' +
          escapeHtml(
            focus
              ? "Following the lineage of " +
                focus.node_id +
                " \u2014 Follow and Hops bound how far it reaches."
              : "Click a node to focus on its lineage, double-click to open "
                + "its page, click a group header to fold it."
          ) +
          "</span>") +
      "</div>"
    );
  }

  /* The key to the drawing, built from the same shapes and tokens the graph
     itself uses, so it cannot drift from what is on screen. Only the kinds
     actually drawn are listed: a project with no missing reference should
     not have to wonder what a red dashed node would have meant. */
  function lineageLegendEntry(label, shape, title) {
    return (
      '<span class="lineage-legend-entry" title="' +
      escapeHtml(title) +
      '">' +
      '<svg width="30" height="16" viewBox="0 0 30 16" aria-hidden="true">' +
      shape +
      "</svg>" +
      escapeHtml(label) +
      "</span>"
    );
  }

  function lineageLegend(present) {
    var entries = [];

    if (present.structure) {
      entries.push(
        lineageLegendEntry(
          "structure",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="var(--accent-soft)" stroke="var(--accent)" />',
          "A table or view: the data itself"
        )
      );
    }
    if (present.flow) {
      entries.push(
        lineageLegendEntry(
          "flow",
          '<polygon points="6,2 24,2 29,8 24,14 6,14 1,8" ' +
            'fill="var(--flow-soft)" stroke="var(--flow)" />',
          "A flow: what reads structures and writes one"
        )
      );
    }
    if (present.group) {
      entries.push(
        lineageLegendEntry(
          "folded namespace",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="hsla(210, 60%, 55%, 0.18)" ' +
            'stroke="hsla(210, 60%, 45%, 0.9)" stroke-width="1.5" />',
          "A namespace folded into one node; click it to unfold"
        )
      );
    }
    if (present.boundary) {
      entries.push(
        lineageLegendEntry(
          "pulled in",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="var(--accent-soft)" stroke="var(--accent)" ' +
            'stroke-dasharray="4 3" opacity="0.7" />',
          "Outside the selection, reached by a traversal"
        )
      );
    }
    if (present.external) {
      entries.push(
        lineageLegendEntry(
          "another project",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="var(--panel-alt)" stroke="var(--text-muted)" ' +
            'stroke-dasharray="2 2" />',
          "Declared by another project of the platform"
        )
      );
    }
    if (present.missing) {
      entries.push(
        lineageLegendEntry(
          "undeclared",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="transparent" stroke="var(--error)" stroke-dasharray="5 3" />',
          "Referenced by a flow but declared nowhere"
        )
      );
    }
    if (present.focused) {
      entries.push(
        lineageLegendEntry(
          "focused",
          '<rect x="1" y="2" width="28" height="12" rx="3" ' +
            'fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2.5" />',
          "The node in focus; everything else is dimmed or hidden"
        )
      );
    }
    if (present.via) {
      entries.push(
        lineageLegendEntry(
          "via a flow",
          '<path d="M1,8 C10,8 20,8 29,8" fill="none" ' +
            'stroke="var(--border)" stroke-width="1.5" />',
          "Structures only: hover the edge for the flow that produces it"
        )
      );
    }

    if (!entries.length) {
      return "";
    }
    return '<div class="lineage-legend">' + entries.join("") + "</div>";
  }

  function lineageZoomControls() {
    return (
      '<div class="lineage-zoom-controls">' +
      '<button type="button" data-lineage-zoom="in" title="Zoom in" aria-label="Zoom in">+</button>' +
      '<button type="button" data-lineage-zoom="out" title="Zoom out" aria-label="Zoom out">−</button>' +
      '<button type="button" data-lineage-zoom="reset" title="Reset the view" aria-label="Reset the view">⟲</button>' +
      "</div>"
    );
  }

  /* ---------------------------------------------------- lineage: grouping */

  function loadLineagePreferences() {
    try {
      var raw = window.localStorage.getItem(LINEAGE_STORAGE_KEY);
      if (!raw) {
        return;
      }
      var stored = JSON.parse(raw);
      if (!stored || typeof stored !== "object") {
        return;
      }
      if (typeof stored.groupDepth === "number") {
        lineageOptions.groupDepth = stored.groupDepth;
      }
      if (stored.collapsedGroups && typeof stored.collapsedGroups === "object") {
        lineageOptions.collapsedGroups = stored.collapsedGroups;
      }
      if (typeof stored.structuresOnly === "boolean") {
        lineageOptions.structuresOnly = stored.structuresOnly;
      }
    } catch (error) {
      /* a private window loses the preference, and nothing else */
    }
  }

  function saveLineagePreferences() {
    try {
      window.localStorage.setItem(
        LINEAGE_STORAGE_KEY,
        JSON.stringify({
          groupDepth: lineageOptions.groupDepth,
          collapsedGroups: lineageOptions.collapsedGroups,
          structuresOnly: lineageOptions.structuresOnly,
        })
      );
    } catch (error) {
      /* storage is a convenience here, never a requirement */
    }
  }

  /* The grouping key is the namespace truncated to `depth` segments counted
     after the selection prefix: descending into clh.business regroups its
     assets on dwh / mart instead of repeating the prefix in every label.
     A depth of 0 means "group on the whole namespace". */
  function namespaceAtDepth(namespace, depth, prefix) {
    var value =
      namespace === null || namespace === undefined || namespace === ""
        ? "."
        : namespace;
    if (value === ".") {
      return ".";
    }
    var base = "";
    var rest = value;
    if (prefix && prefix !== ".") {
      if (value === prefix) {
        return prefix;
      }
      if (value.indexOf(prefix + ".") === 0) {
        base = prefix + ".";
        rest = value.slice(prefix.length + 1);
      }
    }
    var segments = rest.split(".");
    if (!depth || depth >= segments.length) {
      return base + rest;
    }
    return base + segments.slice(0, depth).join(".");
  }

  function groupLabel(groupKey, prefix) {
    if (groupKey === ".") {
      return "root";
    }
    if (prefix && prefix !== "." && groupKey.indexOf(prefix + ".") === 0) {
      return groupKey.slice(prefix.length + 1);
    }
    return groupKey;
  }

  /* A selection that is exactly one namespace clause sets the grouping
     baseline, so the groups of a narrowed graph are its next level down. */
  function selectionNamespacePrefix(selection) {
    var match = /^\s*\d*\+?namespace:"?([A-Za-z0-9_.-]+)"?\+?\d*\s*$/.exec(
      selection || ""
    );
    return match ? match[1] : "";
  }

  function copyLineageNode(node) {
    return {
      key: node.key,
      node_id: node.node_id,
      node_type: node.node_type,
      namespace: node.namespace,
      label: node.label,
      layer: node.layer,
      missing: node.missing,
      sublabel: node.sublabel,
      title: node.title,
    };
  }

  function lineageGroups(nodes, depth, prefix) {
    var groups = {};
    nodes.forEach(function (node) {
      var groupKey = namespaceAtDepth(node.namespace, depth, prefix);
      var group = groups[groupKey];
      if (!group) {
        group = { key: groupKey, structures: 0, flows: 0, layers: [] };
        groups[groupKey] = group;
      }
      group[node.node_type === "flow" ? "flows" : "structures"] += 1;
      group.layers.push(node.layer || 0);
    });
    return groups;
  }

  /* Collapsing one group swaps its members for a single node carrying their
     edges, which is what lets a domain stay folded while its neighbour is
     read in detail. Collapsing every group is the platform-level view. */
  function applyGroupCollapse(lineage, groupKeyByNode, groups, prefix) {
    var collapsedKeys = Object.keys(groups).filter(function (key) {
      return lineageOptions.collapsedGroups[key] === true;
    });
    if (!collapsedKeys.length) {
      return lineage;
    }
    var isCollapsed = {};
    collapsedKeys.forEach(function (key) {
      isCollapsed[key] = true;
    });

    var replacement = {};
    var nodes = [];
    lineage.nodes.forEach(function (node) {
      var groupKey = groupKeyByNode[node.key];
      if (isCollapsed[groupKey]) {
        replacement[node.key] = "group:" + groupKey;
        return;
      }
      replacement[node.key] = node.key;
      nodes.push(copyLineageNode(node));
    });
    collapsedKeys.forEach(function (key) {
      var group = groups[key];
      var label = groupLabel(key, prefix);
      var meanLayer = group.layers.length
        ? Math.round(
            group.layers.reduce(function (total, layer) {
              return total + layer;
            }, 0) / group.layers.length
          )
        : 0;
      nodes.push({
        key: "group:" + key,
        node_id: key,
        node_type: "group",
        namespace: key,
        label: "[" + label + "]",
        layer: meanLayer,
        sublabel: group.structures + " structures, " + group.flows + " flows",
        title:
          "[" +
          label +
          "] " +
          group.structures +
          " structure(s), " +
          group.flows +
          " flow(s) - click to expand",
      });
    });

    var seen = {};
    var edges = [];
    lineage.edges.forEach(function (edge) {
      var source = replacement[edge.source];
      var target = replacement[edge.target];
      if (!source || !target || source === target) {
        return;
      }
      var edgeKey = source + " -> " + target;
      if (seen[edgeKey]) {
        return;
      }
      seen[edgeKey] = true;
      edges.push({ source: source, target: target });
    });

    var layers = longestPathLayers(
      nodes.map(function (node) {
        return node.key;
      }),
      edges
    );
    if (layers) {
      nodes.forEach(function (node) {
        node.layer = layers[node.key] || 0;
      });
    }
    return { nodes: nodes, edges: edges };
  }

  /* Table-level lineage: the flows stop being nodes and become the edges
     they already are. A structure feeds another when some flow reads the
     first and writes the second, so the graph reads as the data model
     rather than as the pipeline - and the reader still sees which flow
     carries each link, on the edge itself. */
  function contractFlows(lineage) {
    var upstream = {};
    var downstream = {};
    lineage.edges.forEach(function (edge) {
      (upstream[edge.target] = upstream[edge.target] || []).push(edge.source);
      (downstream[edge.source] = downstream[edge.source] || []).push(edge.target);
    });

    var nodes = lineage.nodes
      .filter(function (node) {
        return node.node_type !== "flow";
      })
      .map(copyLineageNode);

    var viaByEdge = {};
    var order = [];
    lineage.nodes.forEach(function (node) {
      if (node.node_type !== "flow") {
        return;
      }
      (upstream[node.key] || []).forEach(function (source) {
        (downstream[node.key] || []).forEach(function (target) {
          if (source === target) {
            return;
          }
          var edgeKey = source + " -> " + target;
          if (!viaByEdge[edgeKey]) {
            viaByEdge[edgeKey] = { source: source, target: target, via: [] };
            order.push(edgeKey);
          }
          viaByEdge[edgeKey].via.push(node.node_id);
        });
      });
    });
    var edges = order.map(function (edgeKey) {
      return viaByEdge[edgeKey];
    });

    var layers = longestPathLayers(
      nodes.map(function (node) {
        return node.key;
      }),
      edges
    );
    if (layers) {
      nodes.forEach(function (node) {
        node.layer = layers[node.key] || 0;
      });
    }
    return { nodes: nodes, edges: edges };
  }

  /* Returns null when the graph holds a cycle - namespaces routinely depend
     on each other both ways once collapsed - so the caller can fall back to
     the layer the members already had. */
  function longestPathLayers(nodeIds, edges) {
    var incoming = {};
    var outgoing = {};
    nodeIds.forEach(function (id) {
      incoming[id] = 0;
      outgoing[id] = [];
    });
    edges.forEach(function (edge) {
      incoming[edge.target] += 1;
      outgoing[edge.source].push(edge.target);
    });
    var layers = {};
    var queue = nodeIds.filter(function (id) {
      return incoming[id] === 0;
    });
    var visited = 0;
    while (queue.length) {
      var current = queue.shift();
      visited += 1;
      outgoing[current].forEach(function (next) {
        layers[next] = Math.max(layers[next] || 0, (layers[current] || 0) + 1);
        incoming[next] -= 1;
        if (incoming[next] === 0) {
          queue.push(next);
        }
      });
    }
    if (visited !== nodeIds.length) {
      return null;
    }
    return layers;
  }

  /* --------------------------------------------------- lineage: selection */

  function lineageStatusIndex() {
    var index = {};
    if (!liveState) {
      return index;
    }
    function add(key, status) {
      index[key] = index[key] || {};
      index[key][status] = true;
    }
    (liveState.structure_deployments || []).forEach(function (item) {
      var key = "structure:" + item.structure_id;
      add(key, item.drift ? "drift" : "in-sync");
      if (!item.deployed) {
        add(key, "undeployed");
      }
    });
    (liveState.flow_deployments || []).forEach(function (item) {
      var key = "flow:" + item.flow_id;
      add(key, item.drift ? "drift" : "in-sync");
      if (!item.deployed) {
        add(key, "undeployed");
      }
    });
    (liveState.executions || []).forEach(function (item) {
      var status = String(item.execution_status || "").toUpperCase();
      if (status.indexOf("ERROR") !== -1 || status.indexOf("FAIL") !== -1) {
        add("flow:" + item.flow_id, "failed");
      } else if (status.indexOf("SUCCESS") !== -1) {
        add("flow:" + item.flow_id, "ok");
      }
    });
    (liveState.sla || []).forEach(function (item) {
      if (item.status === "late") {
        add("flow:" + item.flow_id, "late");
      }
    });
    return index;
  }

  function unquote(value) {
    var trimmed = String(value || "").trim();
    if (
      trimmed.length > 1 &&
      trimmed.charAt(0) === '"' &&
      trimmed.charAt(trimmed.length - 1) === '"'
    ) {
      return trimmed.slice(1, -1);
    }
    return trimmed;
  }

  function lineageOwners(node) {
    if (node.node_type === "flow") {
      var flow = flowById[node.node_id];
      return flow && flow.owner ? [flow.owner] : [];
    }
    var structure = structureById[node.node_id];
    if (!structure) {
      return [];
    }
    return (structure.data_owners || []).concat(structure.technical_owners || []);
  }

  function nodeMatchesClause(node, field, value, extra, statusIndex) {
    var needle = String(value || "").toLowerCase();
    if (field === "namespace") {
      return namespaceMatches(node.namespace, value);
    }
    if (field === "type") {
      return node.node_type === needle;
    }
    if (field === "key") {
      var id = node.node_id.toLowerCase();
      if (needle.charAt(needle.length - 1) === "*") {
        return id.indexOf(needle.slice(0, -1)) === 0;
      }
      return id === needle || id.slice(id.lastIndexOf(".") + 1) === needle;
    }
    if (field === "tag") {
      var tagged = structureById[node.node_id];
      return Boolean(
        tagged &&
          (tagged.tags || []).some(function (tag) {
            return String(tag).toLowerCase() === needle;
          })
      );
    }
    if (field === "owner") {
      return lineageOwners(node).some(function (owner) {
        return (
          String(owner.team || "").toLowerCase().indexOf(needle) !== -1 ||
          String(owner.contact || "").toLowerCase().indexOf(needle) !== -1
        );
      });
    }
    if (field === "property") {
      var withProperties = structureById[node.node_id];
      if (!withProperties || !extra) {
        return false;
      }
      return String((withProperties.properties || {})[extra.key]) === extra.value;
    }
    if (field === "status") {
      var statuses = statusIndex[node.key];
      return Boolean(statuses && statuses[needle]);
    }
    return node.node_id.toLowerCase().indexOf(needle) !== -1;
  }

  function tokenizeSelection(text) {
    var tokens = [];
    var value = String(text || "");
    var index = 0;
    while (index < value.length) {
      var character = value.charAt(index);
      if (/\s/.test(character)) {
        index += 1;
        continue;
      }
      if (character === "(" || character === ")") {
        tokens.push({ type: character });
        index += 1;
        continue;
      }
      var start = index;
      var quoted = false;
      while (index < value.length) {
        var current = value.charAt(index);
        if (current === '"') {
          quoted = !quoted;
          index += 1;
          continue;
        }
        if (!quoted && (/\s/.test(current) || current === "(" || current === ")")) {
          break;
        }
        index += 1;
      }
      var raw = value.slice(start, index);
      var lowered = raw.toLowerCase();
      if (lowered === "and" || lowered === "or" || lowered === "not") {
        tokens.push({ type: lowered });
      } else {
        tokens.push({ type: "atom", value: raw });
      }
    }
    return tokens;
  }

  function buildSelectionContext(lineage) {
    var upstream = {};
    var downstream = {};
    lineage.edges.forEach(function (edge) {
      (upstream[edge.target] = upstream[edge.target] || []).push(edge.source);
      (downstream[edge.source] = downstream[edge.source] || []).push(edge.target);
    });
    return {
      nodes: lineage.nodes,
      upstream: upstream,
      downstream: downstream,
      statusIndex: lineageStatusIndex(),
    };
  }

  function evaluateSelection(selection, context) {
    var tokens = tokenizeSelection(selection);
    var position = 0;

    function peek() {
      return tokens[position] || null;
    }

    function expandFrom(base, links, depth) {
      var reached = {};
      var queue = Object.keys(base).map(function (key) {
        return { key: key, distance: 0 };
      });
      while (queue.length) {
        var current = queue.shift();
        (links[current.key] || []).forEach(function (next) {
          var distance = current.distance + 1;
          if (depth && distance > depth) {
            return;
          }
          if (reached[next]) {
            return;
          }
          reached[next] = true;
          queue.push({ key: next, distance: distance });
        });
      }
      return reached;
    }

    function evaluateAtom(raw) {
      var body = raw;
      var upstreamDepth = null;
      var downstreamDepth = null;
      var prefix = /^(\d*)\+/.exec(body);
      if (prefix) {
        upstreamDepth = prefix[1] === "" ? 0 : Number(prefix[1]);
        body = body.slice(prefix[0].length);
      }
      var suffix = /\+(\d*)$/.exec(body);
      if (suffix) {
        downstreamDepth = suffix[1] === "" ? 0 : Number(suffix[1]);
        body = body.slice(0, body.length - suffix[0].length);
      }

      var field = "";
      var value = body;
      var extra = null;
      var separator = body.indexOf(":");
      if (separator !== -1) {
        field = body.slice(0, separator).toLowerCase();
        value = body.slice(separator + 1);
      }
      if (field === "property") {
        var pair = /^"?([^"=]+)"?="?([^"]*)"?$/.exec(value);
        if (!pair) {
          throw new Error('property: expects key="value"');
        }
        extra = { key: pair[1], value: pair[2] };
      }
      value = unquote(value);

      var base = {};
      if (body) {
        context.nodes.forEach(function (node) {
          if (nodeMatchesClause(node, field, value, extra, context.statusIndex)) {
            base[node.key] = true;
          }
        });
      }
      var keys = {};
      Object.keys(base).forEach(function (key) {
        keys[key] = true;
      });
      if (upstreamDepth !== null) {
        Object.keys(expandFrom(base, context.upstream, upstreamDepth)).forEach(
          function (key) {
            keys[key] = true;
          }
        );
      }
      if (downstreamDepth !== null) {
        Object.keys(expandFrom(base, context.downstream, downstreamDepth)).forEach(
          function (key) {
            keys[key] = true;
          }
        );
      }
      return { keys: keys, base: base };
    }

    function applyFunction(name, inner) {
      var links = name === "roots" ? context.upstream : context.downstream;
      var kept = {};
      Object.keys(inner.keys).forEach(function (key) {
        if (!(links[key] || []).length) {
          kept[key] = true;
        }
      });
      return { keys: kept, base: kept };
    }

    function parsePrimary() {
      var token = peek();
      if (!token) {
        throw new Error("the selection ends too early");
      }
      if (token.type === "(") {
        position += 1;
        var inner = parseExpression();
        if (!peek() || peek().type !== ")") {
          throw new Error("a ( is never closed");
        }
        position += 1;
        return inner;
      }
      if (token.type === "not") {
        position += 1;
        var negated = parsePrimary();
        var kept = {};
        context.nodes.forEach(function (node) {
          if (!negated.keys[node.key]) {
            kept[node.key] = true;
          }
        });
        return { keys: kept, base: kept };
      }
      if (token.type !== "atom") {
        throw new Error('unexpected "' + token.type + '"');
      }
      position += 1;
      var lowered = token.value.toLowerCase();
      if (
        (lowered === "roots" || lowered === "sinks") &&
        peek() &&
        peek().type === "("
      ) {
        position += 1;
        var argument = parseExpression();
        if (!peek() || peek().type !== ")") {
          throw new Error("a ( is never closed");
        }
        position += 1;
        return applyFunction(lowered, argument);
      }
      return evaluateAtom(token.value);
    }

    function combine(left, right, operator) {
      var keys = {};
      var base = {};
      if (operator === "or") {
        Object.keys(left.keys)
          .concat(Object.keys(right.keys))
          .forEach(function (key) {
            keys[key] = true;
          });
        Object.keys(left.base)
          .concat(Object.keys(right.base))
          .forEach(function (key) {
            base[key] = true;
          });
        return { keys: keys, base: base };
      }
      Object.keys(left.keys).forEach(function (key) {
        if (right.keys[key]) {
          keys[key] = true;
        }
      });
      Object.keys(keys).forEach(function (key) {
        if (left.base[key] || right.base[key]) {
          base[key] = true;
        }
      });
      return { keys: keys, base: base };
    }

    function parseExpression() {
      var left = parsePrimary();
      while (peek()) {
        var token = peek();
        if (token.type === ")") {
          break;
        }
        var operator = "and";
        if (token.type === "or" || token.type === "and") {
          operator = token.type;
          position += 1;
          if (!peek()) {
            throw new Error('the selection ends after "' + operator + '"');
          }
        }
        left = combine(left, parsePrimary(), operator);
      }
      return left;
    }

    var result = parseExpression();
    if (position < tokens.length) {
      throw new Error("the selection could not be read to its end");
    }
    return result;
  }

  /* Nodes pulled in by a traversal but not matched by the selection itself
     are the boundary of the view, drawn outlined - the same affordance the
     namespace filter had, generalised to every clause. */
  function selectLineage(lineage, selection) {
    if (!String(selection || "").trim()) {
      return {
        nodes: lineage.nodes,
        edges: lineage.edges,
        boundary: {},
        error: null,
      };
    }
    var result;
    try {
      result = evaluateSelection(selection, buildSelectionContext(lineage));
    } catch (error) {
      return {
        nodes: lineage.nodes,
        edges: lineage.edges,
        boundary: {},
        error: error && error.message ? error.message : String(error),
      };
    }
    var boundary = {};
    Object.keys(result.keys).forEach(function (key) {
      if (!result.base[key]) {
        boundary[key] = true;
      }
    });
    return {
      nodes: lineage.nodes.filter(function (node) {
        return result.keys[node.key];
      }),
      edges: lineage.edges.filter(function (edge) {
        return result.keys[edge.source] && result.keys[edge.target];
      }),
      boundary: boundary,
      error: null,
    };
  }

  /* A flow is a verb and a structure is a noun, and the drawing should say
     so without relying on hue alone: structures keep the rectangle that
     reads as a table, flows get the hexagon of the NLD mark - a wheel, with
     as few sides as still reads as one. */
  /* nld names share long prefixes by convention - v_refined_opendata_legal_
     unit_activity, _activity_class, _activity_group - so cutting the tail
     leaves a column of identical labels. Cutting the middle keeps the head
     that says what family it is and the tail that says which one. */
  function elideMiddle(value, limit) {
    var text = String(value === null || value === undefined ? "" : value);
    if (text.length <= limit) {
      return text;
    }
    var tail = Math.ceil((limit - 1) * 0.6);
    var head = limit - 1 - tail;
    return text.slice(0, head) + "\u2026" + text.slice(text.length - tail);
  }

  function lineageNodeShape(position, nodeWidth, nodeHeight, isFlow) {
    if (!isFlow) {
      return (
        '<rect class="lineage-shape" x="' +
        position.x +
        '" y="' +
        position.y +
        '" width="' +
        nodeWidth +
        '" height="' +
        nodeHeight +
        '" rx="6"'
      );
    }
    var chamfer = 16;
    var left = position.x;
    var right = position.x + nodeWidth;
    var top = position.y;
    var bottom = position.y + nodeHeight;
    var middle = position.y + nodeHeight / 2;
    var points = [
      left + chamfer + "," + top,
      right - chamfer + "," + top,
      right + "," + middle,
      right - chamfer + "," + bottom,
      left + chamfer + "," + bottom,
      left + "," + middle,
    ].join(" ");
    return '<polygon class="lineage-shape" points="' + points + '"';
  }

  function pageLineage(focusId) {
    var fullLineage = snapshot.lineage || { nodes: [], edges: [] };
    if (!fullLineage.nodes.length) {
      return "<h1>Lineage</h1>" + card(null, emptyBlock("This project declares no flow."));
    }
    var allNamespaces = namespaceOptions(
      fullLineage.nodes.map(function (node) {
        return node.namespace;
      })
    );

    var baseLineage = lineageOptions.structuresOnly
      ? contractFlows(fullLineage)
      : fullLineage;
    var selected = selectLineage(baseLineage, lineageOptions.selection);
    var boundary = selected.boundary || {};
    var prefix = selectionNamespacePrefix(lineageOptions.selection);
    var groupDepth = lineageOptions.groupDepth;

    var groupKeyByNode = {};
    selected.nodes.forEach(function (node) {
      groupKeyByNode[node.key] = namespaceAtDepth(node.namespace, groupDepth, prefix);
    });
    var groups = lineageGroups(selected.nodes, groupDepth, prefix);
    var groupKeys = Object.keys(groups).sort();

    var lineage = applyGroupCollapse(
      { nodes: selected.nodes, edges: selected.edges },
      groupKeyByNode,
      groups,
      prefix
    );
    lineage.nodes.forEach(function (node) {
      groupKeyByNode[node.key] =
        node.node_type === "group"
          ? node.node_id
          : namespaceAtDepth(node.namespace, groupDepth, prefix);
    });

    var nodeByKey = {};
    lineage.nodes.forEach(function (node) {
      nodeByKey[node.key] = node;
    });
    var focus = null;
    if (focusId) {
      focus =
        nodeByKey[focusId] ||
        lineage.nodes.filter(function (node) {
          return node.node_id === focusId;
        })[0] ||
        null;
    }
    var neighbourhood = focus ? lineageNeighbourhood(lineage, focus.key) : null;

    function inFocus(nodeKey) {
      if (!neighbourhood) {
        return true;
      }
      return withinFocus(neighbourhood, focus.key, nodeKey);
    }

    /* Isolating drops everything the focused node does not depend on and
       everything that does not depend on it, so a wide platform graph reads
       as the single chain the reader is actually asking about. Dimming the
       rest keeps the context; isolating removes it on purpose. */
    var isolated = Boolean(focus) && lineageOptions.isolate;
    if (isolated) {
      lineage = {
        nodes: lineage.nodes.filter(function (node) {
          return inFocus(node.key);
        }),
        edges: lineage.edges.filter(function (edge) {
          return inFocus(edge.source) && inFocus(edge.target);
        }),
      };
      nodeByKey = {};
      lineage.nodes.forEach(function (node) {
        nodeByKey[node.key] = node;
      });
    }

    var byLayer = {};
    lineage.nodes.forEach(function (node) {
      byLayer[node.layer] = byLayer[node.layer] || [];
      byLayer[node.layer].push(node);
    });

    var layers = Object.keys(byLayer)
      .map(Number)
      .sort(function (left, right) {
        return left - right;
      });

    var visibleGroups = {};
    lineage.nodes.forEach(function (node) {
      visibleGroups[groupKeyByNode[node.key]] = true;
    });
    /* Groups are part of the drawing, not an option: a namespace is a path,
       and one box per leaf is no grouping at all on a real project. */
    var grouped = Object.keys(visibleGroups).length > 1;

    var nodeWidth = 190;
    var nodeHeight = 34;
    var gapX = 90;
    var gapY = 16;
    var groupGap = 26;
    var padding = 24;
    var positions = {};
    var groupRects = [];
    var maxHeight = 0;

    layers.forEach(function (layer, layerIndex) {
      var nodes = byLayer[layer].sort(function (left, right) {
        if (grouped) {
          var byGroup = groupKeyByNode[left.key].localeCompare(groupKeyByNode[right.key]);
          if (byGroup !== 0) {
            return byGroup;
          }
        }
        return left.node_id.localeCompare(right.node_id);
      });
      var cursorY = padding;
      var currentGroup = null;
      nodes.forEach(function (node) {
        var groupKey = groupKeyByNode[node.key];
        var collapsedGroup = node.node_type === "group";
        if (
          grouped &&
          !collapsedGroup &&
          (currentGroup === null || currentGroup.groupKey !== groupKey)
        ) {
          if (currentGroup !== null) {
            cursorY += groupGap;
          }
          cursorY += groupGap;
          currentGroup = {
            groupKey: groupKey,
            x: padding + layerIndex * (nodeWidth + gapX) - 8,
            y: cursorY - groupGap + 6,
            width: nodeWidth + 16,
            height: 0,
          };
          groupRects.push(currentGroup);
        }
        if (collapsedGroup) {
          currentGroup = null;
        }
        positions[node.key] = {
          x: padding + layerIndex * (nodeWidth + gapX),
          y: cursorY,
          node: node,
        };
        cursorY += (collapsedGroup ? nodeHeight + 10 : nodeHeight) + gapY;
        if (currentGroup !== null) {
          currentGroup.height = cursorY - gapY + 8 - currentGroup.y;
        }
      });
      maxHeight = Math.max(maxHeight, cursorY);
    });

    var width = padding * 2 + layers.length * (nodeWidth + gapX);
    var height = padding + maxHeight;

    var groupShapes = groupRects
      .map(function (rect) {
        var label = groupLabel(rect.groupKey, prefix);
        return (
          '<g class="lineage-group" data-group-key="' +
          escapeHtml(rect.groupKey) +
          '"><rect x="' +
          rect.x +
          '" y="' +
          rect.y +
          '" width="' +
          rect.width +
          '" height="' +
          rect.height +
          '" rx="8" style="fill: hsla(' +
          namespaceHue(rect.groupKey) +
          ', 60%, 55%, 0.10); stroke: hsla(' +
          namespaceHue(rect.groupKey) +
          ', 60%, 45%, 0.45)" />' +
          '<text class="lineage-group-label" x="' +
          (rect.x + 8) +
          '" y="' +
          (rect.y + 14) +
          '"><title>Fold [' +
          escapeHtml(label) +
          ']</title>&#9662; [' +
          escapeHtml(label) +
          "]</text></g>"
        );
      })
      .join("");

    var edgePaths = lineage.edges
      .map(function (edge) {
        var from = positions[edge.source];
        var to = positions[edge.target];
        if (!from || !to) {
          return "";
        }
        var startX = from.x + nodeWidth;
        var startY = from.y + nodeHeight / 2;
        var endX = to.x;
        var endY = to.y + nodeHeight / 2;
        var midX = (startX + endX) / 2;
        var edgeClass = "lineage-edge";
        if (neighbourhood) {
          edgeClass +=
            inFocus(edge.source) && inFocus(edge.target) ? " highlighted" : " dimmed";
        }
        var path =
          '<path class="' +
          edgeClass +
          '" d="M' +
          startX +
          "," +
          startY +
          " C" +
          midX +
          "," +
          startY +
          " " +
          midX +
          "," +
          endY +
          " " +
          endX +
          "," +
          endY +
          '" />';
        if (!edge.via || !edge.via.length) {
          return path;
        }
        return (
          '<g class="lineage-edge-group"><title>via ' +
          escapeHtml(edge.via.join(", ")) +
          "</title>" +
          path +
          "</g>"
        );
      })
      .join("");

    var nodeShapes = Object.keys(positions)
      .map(function (nodeKey) {
        var position = positions[nodeKey];
        var node = position.node;
        var isFlow = node.node_type === "flow";
        var isGroup = node.node_type === "group";
        var fill = isGroup
          ? "hsla(" + namespaceHue(node.namespace) + ", 60%, 55%, 0.18)"
          : isFlow
            ? "var(--flow-soft)"
            : "var(--accent-soft)";
        var stroke = isGroup
          ? "hsla(" + namespaceHue(node.namespace) + ", 60%, 45%, 0.9)"
          : isFlow
            ? "var(--flow)"
            : "var(--accent)";
        var label = elideMiddle(node.label, 26);
        var nodeClass = "lineage-node" + (isGroup ? " group-node" : "");
        if (neighbourhood) {
          nodeClass += inFocus(nodeKey) ? "" : " dimmed";
          nodeClass += focus.key === nodeKey ? " focused" : "";
        }
        if (boundary[nodeKey]) {
          nodeClass += " boundary";
        }
        if (node.missing) {
          nodeClass += " missing";
        }
        if (node.external) {
          nodeClass += " external";
        }
        var titleText = node.title
          ? node.title
          : "[" +
            namespaceLabel(node.namespace) +
            "] " +
            node.label +
            (node.missing ? " (referenced by a flow but declared nowhere)" : "") +
            (node.external
              ? " (declared by project " + node.external_project + ")"
              : "") +
            (boundary[nodeKey] ? " (pulled in by a traversal)" : "");
        return (
          '<g class="' +
          nodeClass +
          '" data-node-id="' +
          escapeHtml(nodeKey) +
          '" data-node-type="' +
          escapeHtml(node.node_type) +
          '" tabindex="0" role="button"><title>' +
          escapeHtml(titleText) +
          "</title>" +
          lineageNodeShape(
            position,
            nodeWidth,
            isGroup ? nodeHeight + 10 : nodeHeight,
            isFlow
          ) +
          ' fill="' +
          fill +
          '" stroke="' +
          stroke +
          '" />' +
          '<text x="' +
          (position.x + (isFlow ? 18 : 10)) +
          '" y="' +
          (position.y + 21) +
          '" fill="' +
          stroke +
          '">' +
          (isGroup ? "&#9656; " : "") +
          escapeHtml(label) +
          "</text>" +
          (node.sublabel
            ? '<text class="lineage-sublabel" x="' +
              (position.x + (isFlow ? 18 : 10)) +
              '" y="' +
              (position.y + 36) +
              '">' +
              escapeHtml(node.sublabel) +
              "</text>"
            : "") +
          "</g>"
        );
      })
      .join("");

    var focusPanel = "";
    if (focus) {
      var upstreamNodes = neighbourhood.directUpstream
        .map(function (key) {
          return nodeByKey[key];
        })
        .filter(Boolean);
      var downstreamNodes = neighbourhood.directDownstream
        .map(function (key) {
          return nodeByKey[key];
        })
        .filter(Boolean);
      var pageHref =
        focus.node_type === "flow"
          ? "#/flow/" + encodeSegment(focus.node_id)
          : "#/structure/" + encodeSegment(focus.node_id);
      focusPanel = card(
        null,
        "<h2>Focus \u2014 " + displayId(focus.node_id) + "</h2>" +
          '<p><span class="badge ' +
          (focus.node_type === "flow" ? "flow" : "accent") +
          '">' +
          escapeHtml(focus.node_type) +
          "</span> " +
          (focus.node_type === "group"
            ? ""
            : '<a href="' + pageHref + '">Open page</a> \u00b7 ') +
          Object.keys(neighbourhood.ancestors).length +
          " upstream, " +
          Object.keys(neighbourhood.descendants).length +
          " downstream node(s)</p>" +
          '<div class="lineage-focus">' +
          "<div><h3>Directly upstream</h3>" +
          (upstreamNodes.length
            ? "<ul>" +
              upstreamNodes
                .map(function (node) {
                  return "<li>" + lineageNodeLink(node) + "</li>";
                })
                .join("") +
              "</ul>"
            : emptyBlock("Nothing upstream.")) +
          "</div>" +
          "<div><h3>Directly downstream</h3>" +
          (downstreamNodes.length
            ? "<ul>" +
              downstreamNodes
                .map(function (node) {
                  return "<li>" + lineageNodeLink(node) + "</li>";
                })
                .join("") +
              "</ul>"
            : emptyBlock("Nothing downstream.")) +
          "</div></div>"
      );
    }

    var collapsedCount = groupKeys.filter(function (key) {
      return lineageOptions.collapsedGroups[key] === true;
    }).length;
    var subtitle =
      lineage.nodes.length +
      " node(s), " +
      lineage.edges.length +
      " edge(s)" +
      (lineageOptions.selection.trim() && !selected.error
        ? " matching the selection"
        : "") +
      (isolated ? " on the lineage of “" + focus.node_id + "” only" : "") +
      (collapsedCount
        ? ", " + collapsedCount + " group(s) folded"
        : "") +
      (lineageOptions.structuresOnly
        ? ", structures only: each edge carries the flow that produces it"
        : "") +
      ".";

    /* Above the canvas, not below it: the graph is up to 720px tall, so a
       legend under it starts off-screen on the very page it explains. */
    var legend = lineageLegend({
      structure: lineage.nodes.some(function (node) {
        return node.node_type === "structure";
      }),
      flow: lineage.nodes.some(function (node) {
        return node.node_type === "flow";
      }),
      group: lineage.nodes.some(function (node) {
        return node.node_type === "group";
      }),
      boundary: Object.keys(boundary).length > 0,
      external: lineage.nodes.some(function (node) {
        return node.external;
      }),
      missing: lineage.nodes.some(function (node) {
        return node.missing;
      }),
      focused: Boolean(focus),
      via: lineage.edges.some(function (edge) {
        return edge.via && edge.via.length;
      }),
    });

    return (
      "<h1>Lineage</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(subtitle) +
      "</p>" +
      lineageToolbar(allNamespaces, focus, groupKeys.length, selected.error) +
      legend +
      '<div class="lineage-wrapper" id="lineage-wrapper"><svg id="lineage-svg" width="100%" height="' +
      Math.min(height, 720) +
      '" viewBox="0 0 ' +
      width +
      " " +
      height +
      '" role="img" aria-label="Flow lineage" data-width="' +
      width +
      '" data-height="' +
      height +
      '"><g id="lineage-canvas">' +
      groupShapes +
      edgePaths +
      nodeShapes +
      "</g></svg>" +
      lineageZoomControls() +
      "</div>" +
      focusPanel
    );
  }

  function attachLineageInteractions() {
    var svg = document.getElementById("lineage-svg");
    var canvas = document.getElementById("lineage-canvas");
    var wrapper = document.getElementById("lineage-wrapper");
    if (!svg || !canvas || !wrapper) {
      return;
    }

    function applyView() {
      canvas.setAttribute(
        "transform",
        "translate(" +
          lineageView.x +
          "," +
          lineageView.y +
          ") scale(" +
          lineageView.scale +
          ")"
      );
    }

    function zoomBy(factor, centerX, centerY) {
      var next = Math.min(4, Math.max(0.2, lineageView.scale * factor));
      var ratio = next / lineageView.scale;
      lineageView.x = centerX - (centerX - lineageView.x) * ratio;
      lineageView.y = centerY - (centerY - lineageView.y) * ratio;
      lineageView.scale = next;
      applyView();
    }

    function svgPoint(event) {
      var point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      var matrix = svg.getScreenCTM();
      if (!matrix) {
        return { x: 0, y: 0 };
      }
      var transformed = point.matrixTransform(matrix.inverse());
      return { x: transformed.x, y: transformed.y };
    }

    applyView();

    function restoreCaret(selector, caret) {
      var refreshed = document.querySelector(selector);
      if (!refreshed) {
        return;
      }
      refreshed.focus();
      try {
        refreshed.setSelectionRange(caret, caret);
      } catch (error) {
        /* some inputs refuse a selection range; the focus is enough */
      }
    }

    var selectionInput = document.querySelector("[data-lineage-selection]");
    if (selectionInput) {
      var selectionTimer = null;
      selectionInput.addEventListener("input", function () {
        if (selectionTimer) {
          window.clearTimeout(selectionTimer);
        }
        selectionTimer = window.setTimeout(function () {
          selectionTimer = null;
          if (selectionInput.value === lineageOptions.selection) {
            return;
          }
          lineageOptions.selection = selectionInput.value;
          var caret = selectionInput.selectionStart;
          render();
          restoreCaret("[data-lineage-selection]", caret);
        }, 250);
      });
    }

    /* The namespace picker is a shortcut on the selection: picking one
       writes the clause that keeps the namespace and its direct
       neighbours, which is what the old namespace filter did. */
    var namespaceInput = document.querySelector("[data-lineage-namespace]");
    if (namespaceInput) {
      var namespaceTimer = null;
      namespaceInput.addEventListener("input", function () {
        if (namespaceTimer) {
          window.clearTimeout(namespaceTimer);
        }
        namespaceTimer = window.setTimeout(function () {
          namespaceTimer = null;
          var value = namespaceInput.value.trim();
          if (value === selectionNamespacePrefix(lineageOptions.selection)) {
            return;
          }
          lineageOptions.selection = value ? '1+namespace:"' + value + '"+1' : "";
          var caret = namespaceInput.selectionStart;
          render();
          restoreCaret("[data-lineage-namespace]", caret);
        }, 200);
      });
    }

    var groupDepthSelect = document.querySelector("[data-lineage-group-depth]");
    if (groupDepthSelect) {
      groupDepthSelect.addEventListener("change", function () {
        lineageOptions.groupDepth = Number(groupDepthSelect.value);
        saveLineagePreferences();
        render();
      });
    }

    var directionSelect = document.querySelector("[data-lineage-direction]");
    if (directionSelect) {
      directionSelect.addEventListener("change", function () {
        lineageOptions.direction = directionSelect.value;
        render();
      });
    }

    var depthSelect = document.querySelector("[data-lineage-depth]");
    if (depthSelect) {
      depthSelect.addEventListener("change", function () {
        lineageOptions.depth = Number(depthSelect.value);
        render();
      });
    }

    var groupButtons = document.querySelectorAll("[data-lineage-groups]");
    for (var groupIndex = 0; groupIndex < groupButtons.length; groupIndex += 1) {
      groupButtons[groupIndex].addEventListener("click", function (event) {
        var mode = event.currentTarget.getAttribute("data-lineage-groups");
        if (mode === "expand") {
          lineageOptions.collapsedGroups = {};
        } else {
          var collapsed = {};
          var prefix = selectionNamespacePrefix(lineageOptions.selection);
          var fullLineage = snapshot.lineage || { nodes: [], edges: [] };
          var selected = selectLineage(
            lineageOptions.structuresOnly ? contractFlows(fullLineage) : fullLineage,
            lineageOptions.selection
          );
          Object.keys(
            lineageGroups(selected.nodes, lineageOptions.groupDepth, prefix)
          ).forEach(function (key) {
            collapsed[key] = true;
          });
          lineageOptions.collapsedGroups = collapsed;
        }
        saveLineagePreferences();
        render();
      });
    }

    var groupLabels = svg.querySelectorAll(".lineage-group");
    for (var labelIndex = 0; labelIndex < groupLabels.length; labelIndex += 1) {
      (function (element) {
        var groupKey = element.getAttribute("data-group-key");
        element.addEventListener("click", function () {
          if (dragging && dragging.moved) {
            return;
          }
          lineageOptions.collapsedGroups[groupKey] = true;
          saveLineagePreferences();
          render();
        });
      })(groupLabels[labelIndex]);
    }

    var isolateToggle = document.querySelector("[data-lineage-isolate]");
    if (isolateToggle) {
      isolateToggle.addEventListener("change", function () {
        lineageOptions.isolate = isolateToggle.checked;
        render();
      });
    }

    var structuresToggle = document.querySelector("[data-lineage-structures-only]");
    if (structuresToggle) {
      structuresToggle.addEventListener("change", function () {
        lineageOptions.structuresOnly = structuresToggle.checked;
        saveLineagePreferences();
        render();
      });
    }

    var buttons = document.querySelectorAll("[data-lineage-zoom]");
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].addEventListener("click", function (event) {
        var mode = event.currentTarget.getAttribute("data-lineage-zoom");
        var viewBox = svg.viewBox.baseVal;
        var centerX = viewBox.width / 2;
        var centerY = viewBox.height / 2;
        if (mode === "reset") {
          lineageView = { scale: 1, x: 0, y: 0 };
          applyView();
        } else {
          zoomBy(mode === "in" ? 1.25 : 0.8, centerX, centerY);
        }
      });
    }

    svg.addEventListener(
      "wheel",
      function (event) {
        event.preventDefault();
        var point = svgPoint(event);
        zoomBy(event.deltaY < 0 ? 1.1 : 0.9, point.x, point.y);
      },
      { passive: false }
    );

    var dragging = null;
    svg.addEventListener("mousedown", function (event) {
      if (event.button !== 0) {
        return;
      }
      dragging = { x: event.clientX, y: event.clientY, moved: false };
      wrapper.classList.add("panning");
    });
    window.addEventListener("mousemove", function (event) {
      if (!dragging) {
        return;
      }
      var scaleFactor = svg.viewBox.baseVal.width / svg.getBoundingClientRect().width;
      var deltaX = (event.clientX - dragging.x) * scaleFactor;
      var deltaY = (event.clientY - dragging.y) * scaleFactor;
      if (Math.abs(deltaX) + Math.abs(deltaY) > 2) {
        dragging.moved = true;
      }
      lineageView.x += deltaX;
      lineageView.y += deltaY;
      dragging.x = event.clientX;
      dragging.y = event.clientY;
      applyView();
    });
    window.addEventListener("mouseup", function () {
      if (dragging) {
        wrapper.classList.remove("panning");
      }
      dragging = null;
    });

    var nodes = svg.querySelectorAll(".lineage-node");
    for (var nodeIndex = 0; nodeIndex < nodes.length; nodeIndex += 1) {
      (function (element) {
        var nodeId = element.getAttribute("data-node-id");
        var clickTimer = null;
        if (element.getAttribute("data-node-type") === "group") {
          element.addEventListener("click", function () {
            if (dragging && dragging.moved) {
              return;
            }
            delete lineageOptions.collapsedGroups[nodeId.slice("group:".length)];
            saveLineagePreferences();
            render();
          });
          return;
        }
        element.addEventListener("click", function () {
          if (dragging && dragging.moved) {
            return;
          }
          if (clickTimer) {
            return;
          }
          clickTimer = window.setTimeout(function () {
            clickTimer = null;
            window.location.hash = "#/lineage/" + encodeSegment(nodeId);
          }, 220);
        });
        element.addEventListener("dblclick", function () {
          if (clickTimer) {
            window.clearTimeout(clickTimer);
            clickTimer = null;
          }
          var node = (snapshot.lineage.nodes || []).filter(function (item) {
            return item.key === nodeId;
          })[0];
          if (!node) {
            return;
          }
          window.location.hash =
            (node.node_type === "flow" ? "#/flow/" : "#/structure/") +
            encodeSegment(node.node_id);
        });
        element.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            window.location.hash = "#/lineage/" + encodeSegment(nodeId);
          }
        });
      })(nodes[nodeIndex]);
    }
  }

  function searchKinds() {
    var kinds = {};
    searchIndex.forEach(function (item) {
      kinds[item.kind] = (kinds[item.kind] || 0) + 1;
    });
    return Object.keys(kinds).sort();
  }

  function pageSearch(query, kind) {
    var normalised = (query || "").trim();
    if (!normalised) {
      return "<h1>Search</h1>" + card(null, emptyBlock("Type something to search for."));
    }
    var allMatches = searchMatches(normalised, 500, null);
    var counts = {};
    allMatches.forEach(function (item) {
      counts[item.kind] = (counts[item.kind] || 0) + 1;
    });
    var matches = kind
      ? allMatches.filter(function (item) {
          return item.kind === kind;
        })
      : allMatches;
    var filters =
      '<div class="search-filters">' +
      '<button type="button" class="' +
      (kind ? "" : "active") +
      '" data-search-kind="">All (' +
      allMatches.length +
      ")</button>" +
      Object.keys(counts)
        .sort()
        .map(function (item) {
          return (
            '<button type="button" class="' +
            (kind === item ? "active" : "") +
            '" data-search-kind="' +
            escapeHtml(item) +
            '">' +
            escapeHtml(item) +
            " (" +
            counts[item] +
            ")</button>"
          );
        })
        .join("") +
      "</div>";
    return (
      "<h1>Search</h1>" +
      '<p class="page-subtitle">' +
      matches.length +
      ' result(s) for "' +
      escapeHtml(normalised) +
      '"</p>' +
      filters +
      card(
        null,
        table(
          ["Asset", "Kind", "Namespace", "Matched on"],
          matches.slice(0, 200).map(function (item) {
            return [
              '<a href="' + item.href + '">' + highlight(item.name, normalised) + "</a>",
              escapeHtml(item.kind),
              escapeHtml(namespaceLabel(item.namespace)),
              highlight(item.context || "", normalised),
            ];
          })
        )
      )
    );
  }

  function highlight(text, query) {
    var escaped = escapeHtml(text);
    var words = String(query)
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)
      .sort(function (left, right) {
        return right.length - left.length;
      });
    words.forEach(function (word) {
      var pattern = new RegExp("(" + word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      escaped = escaped.replace(pattern, "<mark>$1</mark>");
    });
    return escaped;
  }

  function scoreEntry(entry, words) {
    var total = 0;
    for (var index = 0; index < words.length; index += 1) {
      var word = words[index];
      var best = 0;
      if (entry.nameLower === word) {
        best = 100;
      } else if (entry.nameLower.indexOf(word) === 0) {
        best = 60;
      } else if (entry.nameLower.indexOf(word) !== -1) {
        best = 40;
      }
      if (best < 30) {
        for (var tokenIndex = 0; tokenIndex < entry.tokens.length; tokenIndex += 1) {
          var token = entry.tokens[tokenIndex];
          if (token === word) {
            best = Math.max(best, 30);
            break;
          }
          if (token.indexOf(word) === 0) {
            best = Math.max(best, 20);
          }
        }
      }
      if (best === 0 && entry.haystack.indexOf(word) !== -1) {
        best = 10;
      }
      if (best === 0) {
        return 0;
      }
      total += best;
    }
    return total + entry.boost;
  }

  function searchMatches(query, limit, kind) {
    var words = String(query || "")
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    if (!words.length) {
      return [];
    }
    var scored = [];
    searchIndex.forEach(function (entry) {
      if (kind && entry.kind !== kind) {
        return;
      }
      var score = scoreEntry(entry, words);
      if (score > 0) {
        scored.push({ entry: entry, score: score });
      }
    });
    scored.sort(function (left, right) {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      return left.entry.name.localeCompare(right.entry.name);
    });
    return scored.slice(0, limit).map(function (item) {
      return item.entry;
    });
  }

  function stateUnavailableNotice(detail) {
    return (
      "<h1>Live state</h1>" +
      card(
        null,
        "<p>This export was generated with <code class='inline'>nld docs build</code> or " +
          "<code class='inline'>nld docs deploy</code>: it carries the project as written, with no " +
          "backend access.</p><p>Run <code class='inline'>nld docs serve</code> from the project to get " +
          "deployment state, executions, SLA and freshness read from the configured environment." +
          (detail ? ' <span class="muted">(' + escapeHtml(detail) + ")</span>" : "") +
          "</p>"
      )
    );
  }

  function pageState() {
    if (stateApiEnabled === false) {
      return stateUnavailableNotice(liveStateError);
    }
    if (!liveStateLoaded) {
      loadLiveState(false);
      return "<h1>Live state</h1>" + card(null, emptyBlock("Reading the backends…"));
    }
    if (liveStateError) {
      return stateUnavailableNotice(liveStateError);
    }

    var state = liveState || {};
    var backend = state.backend || {};
    var backendSection = backend.section || {};

    var structureRows = (state.structure_deployments || []).map(function (item) {
      return [
        structureLink(item.structure_id),
        item.deployed
          ? '<span class="badge ok">deployed</span>'
          : '<span class="badge warn">not deployed</span>',
        item.drift ? '<span class="badge error">drift</span>' : '<span class="badge ok">in sync</span>',
        formatDate(item.deployed_at),
        "<code class='inline'>" + escapeHtml((item.deployed_hash || "—").slice(0, 12)) + "</code>",
        "<code class='inline'>" + escapeHtml((item.repository_hash || "—").slice(0, 12)) + "</code>",
      ];
    });

    var flowRows = (state.flow_deployments || []).map(function (item) {
      return [
        flowLink(item.flow_id),
        item.deployed
          ? '<span class="badge ok">deployed</span>'
          : '<span class="badge warn">not deployed</span>',
        item.drift ? '<span class="badge error">drift</span>' : '<span class="badge ok">in sync</span>',
        formatDate(item.deployed_at),
        "<code class='inline'>" + escapeHtml((item.deployed_yaml_hash || "—").slice(0, 12)) + "</code>",
      ];
    });

    var executionRows = (state.executions || []).map(function (item) {
      return [
        flowLink(item.flow_id),
        item.reached ? statusBadge(item.execution_status) : '<span class="badge warn">unreachable</span>',
        formatDate(item.started_at),
        formatDuration(item.duration_seconds),
        escapeHtml(item.execution_error || item.message || ""),
      ];
    });

    var tolerance = null;
    var slaRows = (state.sla || []).map(function (item) {
      if (item.tolerance_ratio) {
        tolerance = item.tolerance_ratio;
      }
      return [
        flowLink(item.flow_id),
        escapeHtml(item.environment || "—"),
        escapeHtml(item.frequency || "—") +
          (item.expected_interval_seconds
            ? ' <span class="muted">(≤ ' + formatDuration(item.expected_interval_seconds * (item.tolerance_ratio || 1)) + ")</span>"
            : ""),
        slaBadge(item.status),
        statusBadge(item.last_status),
        formatDate(item.last_success_at),
        item.age_seconds === null || item.age_seconds === undefined
          ? "—"
          : formatDuration(item.age_seconds),
      ];
    });
    var slaNote = tolerance
      ? '<p class="muted" style="margin-bottom:0">A flow is late once its last success is older than ' +
        tolerance +
        "× the interval its declared frequency implies; the bracket shows that limit. Failed and running reflect the latest attempt.</p>"
      : "";

    var freshnessRows = (state.freshness || []).map(function (item) {
      return [
        structureLink(item.structure_id),
        formatDate(item.last_updated_at),
        item.age_seconds === null || item.age_seconds === undefined
          ? "—"
          : formatDuration(item.age_seconds),
        escapeHtml(item.source || ""),
        flowLink(item.produced_by),
      ];
    });

    return (
      "<h1>Live state</h1>" +
      '<p class="page-subtitle">' +
      escapeHtml(
        "Collected " +
          formatDate(state.collected_at) +
          (state.environment ? " for environment " + state.environment : "")
      ) +
      ' <button type="button" class="inline-button" data-state-refresh="1">Refresh now</button>' +
      "</p>" +
      (state.message ? card(null, "<p>" + escapeHtml(state.message) + "</p>") : "") +
      card(
        "Metadata backend",
        definitionList([
          ["Status", sectionBadge(backendSection)],
          ["Detail", escapeHtml(backendSection.message)],
          ["Connection", escapeHtml(backend.connection_name)],
          ["Connector type", escapeHtml(backend.connector_type)],
          ["Metadata schema", escapeHtml(backend.metadata_schema)],
        ])
      ) +
      cardWithBadge(
        "Structure deployments",
        sectionBadge(state.deployment_section || {}),
        table(
          ["Structure", "Deployment", "Drift", "Deployed at", "Deployed hash", "Repository hash"],
          structureRows
        )
      ) +
      card(
        "Flow deployments",
        table(["Flow", "Deployment", "Drift", "Deployed at", "Deployed hash"], flowRows)
      ) +
      cardWithBadge(
        "Flow executions",
        sectionBadge(state.execution_section || {}),
        table(["Flow", "Status", "Started", "Duration", "Detail"], executionRows)
      ) +
      card(
        "SLA",
        table(
          ["Flow", "Environment", "Frequency", "Status", "Last run", "Last success", "Age"],
          slaRows
        ) + slaNote
      ) +
      card(
        "Data freshness",
        table(["Structure", "Last updated", "Age", "Signal", "Produced by"], freshnessRows)
      )
    );
  }

  function sectionBadge(section) {
    if (!section || !section.status) {
      return "";
    }
    if (section.status === "ok") {
      return '<span class="badge ok">ok</span>';
    }
    return (
      '<span class="badge warn" title="' +
      escapeHtml(section.message || "") +
      '">unavailable</span>'
    );
  }

  function statusBadge(status) {
    if (!status) {
      return '<span class="badge">—</span>';
    }
    var upper = String(status).toUpperCase();
    if (upper === "SUCCEEDED") {
      return '<span class="badge ok">' + escapeHtml(status) + "</span>";
    }
    if (upper === "WARNING") {
      return '<span class="badge ok" title="succeeded with warnings">' + escapeHtml(status) + "</span>";
    }
    if (upper === "FAILED" || upper.indexOf("ERROR") !== -1) {
      return '<span class="badge error">' + escapeHtml(status) + "</span>";
    }
    return '<span class="badge warn">' + escapeHtml(status) + "</span>";
  }

  function slaBadge(status) {
    if (status === "on_time") {
      return '<span class="badge ok">on time</span>';
    }
    if (status === "late") {
      return '<span class="badge error">late</span>';
    }
    if (status === "failed") {
      return '<span class="badge error">failed</span>';
    }
    if (status === "running") {
      return '<span class="badge warn">running</span>';
    }
    if (status === "never_run") {
      return '<span class="badge warn">never run</span>';
    }
    return '<span class="badge">unknown</span>';
  }

  function notFound(kind, identifier) {
    return (
      "<h1>Not found</h1>" +
      card(
        null,
        "<p>" +
          escapeHtml("No " + kind + " named " + identifier + " in this snapshot.") +
          "</p>"
      )
    );
  }

  /* ----------------------------------------------------------- live state */

  function stateSource() {
    return siteConfig.state_source || "api";
  }

  function stateEndpoint(refresh) {
    if (stateSource() === "file") {
      return siteConfig.state_url || "./state.json";
    }
    var base = siteConfig.state_url || "./api/state";
    return base + (refresh ? (base.indexOf("?") === -1 ? "?" : "&") + "refresh=1" : "");
  }

  function loadLiveState(refresh) {
    liveStateLoaded = true;
    if (stateSource() === "none") {
      liveStateError = "this site was published without a state source";
      render();
      return;
    }
    if (typeof fetch !== "function") {
      liveStateError = "this browser cannot call the state API";
      render();
      return;
    }
    fetch(stateEndpoint(refresh))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        liveState = payload;
        liveStateError = null;
        render();
      })
      .catch(function (error) {
        liveStateError = error && error.message ? error.message : String(error);
        render();
      });
  }

  /* A platform is several nld projects, and a reader lands in whichever one
     the link pointed at. The switcher is written by `nld docs catalog build`
     and is simply absent from a single-project site. */
  function renderProjectSwitcher() {
    var projects = siteConfig.projects || [];
    var host = document.getElementById("project-name");
    if (!host || projects.length < 2) {
      return;
    }
    var current = siteConfig.project_name;
    host.innerHTML =
      '<select class="project-switcher" aria-label="Project">' +
      projects
        .map(function (project) {
          return (
            '<option value="' +
            escapeHtml(project.href) +
            '"' +
            (project.name === current ? " selected" : "") +
            ">" +
            escapeHtml(project.title || project.name) +
            "</option>"
          );
        })
        .join("") +
      "</select>";
    var select = host.querySelector(".project-switcher");
    if (select) {
      select.addEventListener("change", function () {
        window.location.href = select.value;
      });
    }
  }

  function probeStateApi() {
    /* A published site declares its state source up front, so there is
       nothing to probe: only a served site has a health endpoint. */
    if (stateSource() === "none") {
      stateApiEnabled = false;
      liveStateError = "this site was published without a state source";
      buildNav();
      return;
    }
    if (stateSource() === "file") {
      stateApiEnabled = true;
      buildNav();
      return;
    }
    if (typeof fetch !== "function") {
      stateApiEnabled = false;
      buildNav();
      return;
    }
    fetch("./api/health")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        stateApiEnabled = Boolean(payload && payload.state_enabled);
        if (!stateApiEnabled) {
          liveStateError = "the server runs without the live-state layer";
        }
        buildNav();
        highlightNav(parseRoute());
      })
      .catch(function () {
        stateApiEnabled = false;
        buildNav();
        highlightNav(parseRoute());
      });
  }

  /* --------------------------------------------------------------- router */

  function parseRoute() {
    var hash = window.location.hash.replace(/^#/, "");
    if (!hash || hash === "/") {
      return { name: "overview", params: [] };
    }
    var parts = hash.replace(/^\//, "").split("/").map(decodeURIComponent);
    return { name: parts[0], params: parts.slice(1) };
  }

  function routeToHtml(route) {
    switch (route.name) {
      case "structures":
        return pageStructures();
      case "structure":
        return pageStructure(route.params[0]);
      case "lineage":
        return pageLineage(route.params[0]);
      case "flows":
        return pageFlows();
      case "flow":
        return pageFlow(route.params[0]);
      case "namespaces":
        return pageNamespaces();
      case "namespace":
        return pageNamespace(route.params[0]);
      case "entities":
        return pageEntities(route.params[0]);
      case "entity":
        return pageEntity(route.params[0], route.params[1]);
      case "state":
        return pageState();
      case "coverage":
        return pageCoverage();
      case "search":
        return pageSearch(route.params[0] || "", route.params[1] || null);
      default:
        return pageOverview();
    }
  }

  function render() {
    var route = parseRoute();
    contentEl.innerHTML = routeToHtml(route);
    window.scrollTo(0, 0);
    highlightNav(route);
    attachNamespacePickers();
    attachFilters();
    attachLineageInteractions();
    attachSearchFilters(route);
    attachStateRefresh();
    scrollToAnchor(route);
  }

  function attachStateRefresh() {
    var button = document.querySelector("[data-state-refresh]");
    if (!button) {
      return;
    }
    button.addEventListener("click", function () {
      liveStateLoaded = false;
      liveState = null;
      contentEl.innerHTML = "<h1>Live state</h1>" + card(null, emptyBlock("Reading the backends…"));
      loadLiveState(true);
    });
  }

  function attachSearchFilters(route) {
    var buttons = document.querySelectorAll("[data-search-kind]");
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].addEventListener("click", function (event) {
        var kind = event.currentTarget.getAttribute("data-search-kind");
        window.location.hash =
          "#/search/" + encodeSegment(route.params[0] || "") + (kind ? "/" + encodeSegment(kind) : "");
      });
    }
  }

  function scrollToAnchor(route) {
    var anchorId = null;
    if (route.name === "structure" && route.params[1] === "field" && route.params[2]) {
      anchorId = "field-" + route.params[2];
    }
    if (route.name === "entity" && route.params[2] === "term" && route.params[3]) {
      anchorId = "term-" + route.params[3];
    }
    if (!anchorId) {
      return;
    }
    var element = document.getElementById(anchorId);
    if (element) {
      element.scrollIntoView({ block: "center" });
      var row = element.closest("tr");
      if (row) {
        row.style.background = "var(--accent-soft)";
      }
    }
  }

  function highlightNav(route) {
    var links = navEl.querySelectorAll("a");
    for (var index = 0; index < links.length; index += 1) {
      var link = links[index];
      var target = link.getAttribute("href").replace(/^#/, "").replace(/^\//, "");
      var current = route.name || "";
      var active = target.split("/")[0] === current;
      if (current === "entities" || current === "entity") {
        active = target === "entities/" + encodeSegment(route.params[0] || "");
      }
      link.className = active ? "active" : "";
    }
  }

  /* ------------------------------------------------------------------ nav */

  function buildNav() {
    var counts = snapshot.counts || {};
    var html = [
      '<a href="#/"><span>Overview</span></a>',
      '<a href="#/namespaces"><span>Namespaces</span><span class="count">' +
        (snapshot.namespaces || []).length +
        "</span></a>",
      '<a href="#/structures"><span>Structures</span><span class="count">' +
        (counts.structure || 0) +
        "</span></a>",
      '<a href="#/flows"><span>Flows</span><span class="count">' +
        (counts.flows || 0) +
        "</span></a>",
      '<a href="#/lineage"><span>Lineage</span></a>',
    ];
    if (stateApiEnabled !== false) {
      html.push('<a href="#/state"><span>Live state</span></a>');
    }

    var grouped = {};
    (snapshot.entity_types || []).forEach(function (entityType) {
      if (entityType.name === "structure" || entityType.name === "flows") {
        return;
      }
      var list = entitiesByType[entityType.name] || [];
      if (!list.length) {
        return;
      }
      var category = entityType.category || "other";
      grouped[category] = grouped[category] || [];
      grouped[category].push(entityType);
    });

    Object.keys(grouped)
      .sort()
      .forEach(function (category) {
        html.push('<div class="nav-group">' + escapeHtml(category) + "</div>");
        grouped[category].forEach(function (entityType) {
          html.push(
            '<a href="#/entities/' +
              encodeSegment(entityType.name) +
              '"><span>' +
              escapeHtml(entityType.display_name) +
              '</span><span class="count">' +
              ((entitiesByType[entityType.name] || []).length) +
              "</span></a>"
          );
        });
      });

    navEl.innerHTML = html.join("");
  }

  /* ---------------------------------------------------------------- index */

  function tokenise(values) {
    var tokens = {};
    values.forEach(function (value) {
      if (value === null || value === undefined) {
        return;
      }
      String(value)
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(Boolean)
        .forEach(function (token) {
          tokens[token] = true;
        });
    });
    return Object.keys(tokens);
  }

  function indexEntry(entry) {
    var keywords = entry.keywords || [];
    var haystack = [entry.name, entry.namespace || ""]
      .concat(keywords)
      .concat(entry.text || [])
      .join(" ")
      .toLowerCase();
    searchIndex.push({
      name: entry.name,
      nameLower: String(entry.name).toLowerCase(),
      kind: entry.kind,
      namespace: entry.namespace,
      href: entry.href,
      context: entry.context || "",
      tokens: tokenise([entry.name].concat(keywords)),
      haystack: haystack,
      boost: entry.boost || 0,
    });
  }

  function flattenFields(fields, collected) {
    (fields || []).forEach(function (field) {
      collected.push(field);
      flattenFields(field.fields, collected);
    });
    return collected;
  }

  function buildIndexes() {
    (snapshot.structures || []).forEach(function (structure) {
      structureById[structure.node_id] = structure;
      var fields = flattenFields(structure.fields, []);
      indexEntry({
        name: structure.name,
        kind: "structure",
        namespace: structure.namespace,
        href: "#/structure/" + encodeSegment(structure.node_id),
        context: structure.short_description || structure.description || structure.node_id,
        keywords: [structure.node_id, structure.structure_type, structure.short_name]
          .concat(structure.tags || [])
          .concat(structure.templates || [])
          .concat(structure.primary_key_fields || [])
          .concat(
            fields.map(function (field) {
              return field.name;
            })
          ),
        text: [structure.description, structure.short_description]
          .concat(
            (structure.data_owners || []).concat(structure.technical_owners || []).map(function (owner) {
              return owner.team;
            })
          )
          .concat(
            Object.keys(structure.properties || {}).map(function (key) {
              return key + " " + structure.properties[key];
            })
          )
          .concat(
            Object.keys(structure.business_metadata || {}).map(function (key) {
              return key + " " + structure.business_metadata[key];
            })
          ),
        boost: 5,
      });
      fields.forEach(function (field) {
        indexEntry({
          name: field.name,
          kind: "field",
          namespace: structure.namespace,
          href:
            "#/structure/" +
            encodeSegment(structure.node_id) +
            "/field/" +
            encodeSegment(field.name),
          context: structure.node_id + " · " + (field.data_type || ""),
          keywords: [structure.node_id, field.data_type, field.from_template].concat(
            field.characterisations || []
          ),
          text: [field.description, field.short_description],
        });
      });
    });

    (snapshot.flows || []).forEach(function (flow) {
      flowById[flow.node_id] = flow;
      indexEntry({
        name: flow.name,
        kind: "flow",
        namespace: flow.namespace,
        href: "#/flow/" + encodeSegment(flow.node_id),
        context: flow.target_structure ? "→ " + flow.target_structure : flow.node_id,
        keywords: [
          flow.node_id,
          flow.target_structure,
          flow.write_strategy,
          flow.task_type,
          flow.task,
          flow.incremental && flow.incremental.type,
        ]
          .concat(
            (flow.predecessors || []).map(function (predecessor) {
              return predecessor.full_path;
            })
          )
          .concat(
            (flow.schedules || []).map(function (schedule) {
              return schedule.environment;
            })
          )
          .concat(Object.keys(flow.field_lineage || {})),
        text: [flow.owner ? flow.owner.team : ""].concat(
          (flow.documentation || []).map(function (block) {
            return block.content;
          })
        ),
        boost: 5,
      });
    });

    (snapshot.namespaces || []).forEach(function (namespace) {
      namespaceByName[namespace.namespace] = namespace;
      indexEntry({
        name: namespaceLabel(namespace.namespace),
        kind: "namespace",
        namespace: namespace.namespace,
        href: "#/namespace/" + encodeSegment(namespace.namespace),
        context:
          Object.keys(namespace.entity_counts || {})
            .map(function (key) {
              return key + ": " + namespace.entity_counts[key];
            })
            .join(", ") || "namespace",
        keywords: [namespace.namespace],
        text: (namespace.documentation || []).map(function (block) {
          return block.content;
        }),
      });
    });

    (snapshot.entity_types || []).forEach(function (entityType) {
      if (entityType.name === "structure" || entityType.name === "flows") {
        return;
      }
      if (!(entitiesByType[entityType.name] || []).length) {
        return;
      }
      indexEntry({
        name: entityType.display_name,
        kind: "entity type",
        namespace: ".",
        href: "#/entities/" + encodeSegment(entityType.name),
        context: entityType.count + " asset(s) · " + entityType.folder_name,
        keywords: [entityType.name, entityType.category, entityType.folder_name],
      });
    });

    Object.keys(entitiesByType).forEach(function (entityType) {
      (entitiesByType[entityType] || []).forEach(function (entity) {
        var payload = entity.payload || {};
        var extra = [];
        if (payload.field && payload.field.name) {
          extra.push(payload.field.name, payload.field.data_type);
        }
        if (payload.field_templates) {
          extra = extra.concat(payload.field_templates);
        }
        if (payload.tags) {
          extra = extra.concat(payload.tags);
        }
        if (payload.team) {
          extra.push(payload.team);
        }
        indexEntry({
          name: entity.name,
          kind: entity.display_name.toLowerCase(),
          namespace: entity.namespace,
          href: "#/entity/" + encodeSegment(entityType) + "/" + encodeSegment(entity.node_id),
          context: entity.description || entity.node_id,
          keywords: [entity.node_id, entity.category].concat(extra),
          text: [entity.description].concat(
            (entity.documentation || []).map(function (block) {
              return block.content;
            })
          ),
        });
      });
    });

    (snapshot.terms || []).forEach(function (term) {
      (termsByDictionary[term.dictionary_node_id] =
        termsByDictionary[term.dictionary_node_id] || []).push(term);
      var translationNames = [];
      (term.translations || []).forEach(function (translation) {
        translationNames.push(translation.name, translation.plural);
        translationNames = translationNames.concat(translation.synonyms || []);
      });
      indexEntry({
        name: term.name,
        kind: "business term",
        namespace: term.namespace,
        href:
          "#/entity/business_dictionary/" +
          encodeSegment(term.dictionary_node_id) +
          "/term/" +
          encodeSegment(term.name),
        context: term.description || term.dictionary,
        keywords: [term.plural, term.dictionary]
          .concat(term.synonyms || [])
          .concat(term.related_terms || [])
          .concat(translationNames),
        text: [term.description],
        boost: 3,
      });
    });
  }

  /* ----------------------------------------------------------------- boot */

  function initTheme() {
    var stored = null;
    try {
      stored = window.localStorage.getItem("nld-docs-theme");
    } catch (error) {
      stored = null;
    }
    var prefersDark =
      window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute(
      "data-theme",
      stored || (prefersDark ? "dark" : "light")
    );

    var toggle = document.getElementById("theme-toggle");
    toggle.addEventListener("click", function () {
      var next =
        document.documentElement.getAttribute("data-theme") === "dark"
          ? "light"
          : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem("nld-docs-theme", next);
      } catch (error) {
        /* storage is a convenience here, never a requirement */
      }
    });
  }

  function initSearch() {
    var container = searchInput.parentNode;
    var results = document.createElement("div");
    results.className = "search-results";
    results.hidden = true;
    container.appendChild(results);
    var timer = null;

    function close() {
      results.hidden = true;
      results.innerHTML = "";
      searchSelection = -1;
    }

    function renderResults() {
      var query = searchInput.value.trim();
      if (!query) {
        close();
        return;
      }
      var matches = searchMatches(query, 12, null);
      searchSelection = -1;
      if (!matches.length) {
        results.innerHTML = '<div class="result-empty">No asset matches.</div>';
        results.hidden = false;
        return;
      }
      results.innerHTML =
        matches
          .map(function (item) {
            return (
              '<a href="' +
              item.href +
              '"><span class="result-name">' +
              highlight(item.name, query) +
              '</span><span class="result-meta"><span class="result-kind">' +
              escapeHtml(item.kind) +
              "</span>" +
              escapeHtml(namespaceLabel(item.namespace)) +
              (item.context ? " · " + escapeHtml(item.context) : "") +
              "</span></a>"
            );
          })
          .join("") +
        '<a href="#/search/' +
        encodeSegment(query) +
        '"><span class="result-meta">All results for "' +
        escapeHtml(query) +
        '" ↵</span></a>';
      results.hidden = false;
    }

    function moveSelection(delta) {
      var links = results.querySelectorAll("a");
      if (!links.length) {
        return;
      }
      searchSelection = (searchSelection + delta + links.length) % links.length;
      for (var index = 0; index < links.length; index += 1) {
        links[index].className = index === searchSelection ? "selected" : "";
      }
      links[searchSelection].scrollIntoView({ block: "nearest" });
    }

    searchInput.addEventListener("input", function () {
      if (timer) {
        window.clearTimeout(timer);
      }
      timer = window.setTimeout(renderResults, 80);
    });
    searchInput.addEventListener("focus", renderResults);
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(-1);
      } else if (event.key === "Escape") {
        close();
      } else if (event.key === "Enter") {
        var links = results.querySelectorAll("a");
        if (searchSelection >= 0 && links[searchSelection]) {
          window.location.hash = links[searchSelection].getAttribute("href");
        } else {
          window.location.hash = "#/search/" + encodeSegment(searchInput.value.trim());
        }
        close();
      }
    });
    results.addEventListener("click", function () {
      close();
    });
    document.addEventListener("click", function (event) {
      if (!container.contains(event.target)) {
        close();
      }
    });
  }

  function init() {
    renderProjectSwitcher();
    document.getElementById("project-name").textContent =
      (snapshot.project && snapshot.project.name) || "unknown project";
    document.getElementById("generated-at").textContent =
      "generated " + formatDate(snapshot.meta && snapshot.meta.generated_at);
    buildIndexes();
    buildNav();
    loadLineagePreferences();
    initTheme();
    initSearch();
    window.addEventListener("hashchange", render);
    render();
    probeStateApi();
  }

  init();

  /* The pure rendering functions are exposed for the node test-suite only;
     the page itself never reads this object. */
  window.NLD_DOCS_TEST_API = {
    escapeHtml: escapeHtml,
    highlightSql: highlightSql,
    parseRoute: parseRoute,
    render: render,
    renderMarkdown: renderMarkdown,
    routeToHtml: routeToHtml,
    safeHref: safeHref,
    searchMatches: searchMatches,
    displayId: displayId,
    namespaceMatches: namespaceMatches,
    setLineageOptions: function (options) {
      Object.keys(options).forEach(function (key) {
        lineageOptions[key] = options[key];
      });
    },
    setStateApiEnabled: function (enabled) {
      stateApiEnabled = enabled;
      buildNav();
    },
    setLiveState: function (state, error) {
      liveState = state;
      liveStateError = error || null;
      liveStateLoaded = true;
    },
  };
})();
