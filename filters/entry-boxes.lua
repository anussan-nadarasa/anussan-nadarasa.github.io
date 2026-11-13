--[[
entry-boxes.lua

For any page whose front matter has a `type:` field (i.e. an entry), adds:
  * a small type label and the "How AI was used" box at the top
  * an "Evidence" list and a link to the page's full git history at the bottom

Front matter it reads:

  type: project            # log | project | course | paper | reflection | essay
  evidence:
    - label: Code
      url: https://github.com/...
  ai:
    tools: [Claude Opus 5.5]
    did: What the AI did.
    me: What you did and how you checked it.
  # or simply:  ai: none
  worklog: project-name    # optional: worklogs/project-name.json, from scripts/export_worklog.py
]]

local str = pandoc.utils.stringify

local function as_list(x)
  if x == nil then return {} end
  if pandoc.utils.type(x) == "List" then return x end
  return { x }
end

local function para(inlines_or_text)
  if type(inlines_or_text) == "string" then
    return pandoc.Para(pandoc.Inlines(inlines_or_text))
  end
  return pandoc.Para(inlines_or_text)
end

local function ai_box(ai)
  local blocks = pandoc.Blocks({})
  local t = pandoc.utils.type(ai)

  if t ~= "table" and t ~= "Meta" then
    -- scalar, e.g. "none"
    local s = str(ai)
    if s:lower() == "none" or s == "" then
      blocks:insert(para("No generative AI was used for this entry."))
    else
      blocks:insert(para(s))
    end
  else
    local tools = {}
    for _, v in ipairs(as_list(ai.tools)) do table.insert(tools, str(v)) end
    if #tools > 0 then
      blocks:insert(pandoc.Para({ pandoc.Strong("Tools: "), pandoc.Str(table.concat(tools, ", ")) }))
    end
    if ai.did then
      local p = pandoc.List({ pandoc.Strong("AI did: ") })
      p:extend(pandoc.utils.type(ai.did) == "Inlines" and ai.did or pandoc.Inlines(str(ai.did)))
      blocks:insert(pandoc.Para(p))
    end
    if ai.me then
      local p = pandoc.List({ pandoc.Strong("Author did and checked: ") })
      p:extend(pandoc.utils.type(ai.me) == "Inlines" and ai.me or pandoc.Inlines(str(ai.me)))
      blocks:insert(pandoc.Para(p))
    end
  end

  if quarto and quarto.Callout then
    return (quarto.Callout({ type = "note", title = "How AI was used", icon = false, content = blocks }))
  end
  return pandoc.Div(blocks, pandoc.Attr("", { "callout-note" }, { title = "How AI was used", icon = "false" }))
end

local function evidence_list(evidence)
  local items = {}
  for _, e in ipairs(as_list(evidence)) do
    if pandoc.utils.type(e) == "table" or pandoc.utils.type(e) == "Meta" then
      local label = e.label and str(e.label) or "Link"
      local url = e.url and str(e.url) or ""
      if url ~= "" then
        table.insert(items, { pandoc.Plain({ pandoc.Link(label, url) }) })
      end
    else
      local url = str(e)
      table.insert(items, { pandoc.Plain({ pandoc.Link(url, url) }) })
    end
  end
  if #items == 0 then return nil end
  return pandoc.Blocks({ pandoc.Header(2, "Evidence", pandoc.Attr("evidence")), pandoc.BulletList(items) })
end

local function relative_source_path()
  if not (quarto and quarto.doc and quarto.doc.input_file and quarto.project and quarto.project.directory) then
    return nil
  end
  local input, root = quarto.doc.input_file, quarto.project.directory
  if input:sub(1, #root) ~= root then return nil end
  local rel = input:sub(#root + 2)
  return (rel:gsub("\\", "/"))
end

-- ---------------------------------------------------------------------------
-- Work log: rendered from worklogs/<name>.json (made by scripts/export_worklog.py)
-- ---------------------------------------------------------------------------

local function esc(s)
  return (tostring(s):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

local function day_number(iso)
  local y, m, d = iso:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)")
  return math.floor(os.time({ year = tonumber(y), month = tonumber(m), day = tonumber(d), hour = 12 }) / 86400)
end

local MONTHS = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" }
local function nice_date(iso)
  local y, m, d = iso:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)")
  return tonumber(d) .. " " .. MONTHS[tonumber(m)] .. " " .. y
end

local function weekly_chart(commits, first_day, n_weeks)
  local counts = {}
  for i = 1, n_weeks do counts[i] = 0 end
  local max = 1
  for _, c in ipairs(commits) do
    local w = math.floor((day_number(c.date) - first_day) / 7) + 1
    counts[w] = (counts[w] or 0) + 1
    if counts[w] > max then max = counts[w] end
  end
  local width, height = 640, 56
  local bw = math.min(width / n_weeks, 28)
  local parts = { string.format(
    '<svg class="worklog-chart" viewBox="0 0 %d %d" preserveAspectRatio="none" role="img" aria-label="Commits per week">',
    width, height) }
  for i = 1, n_weeks do
    local h = counts[i] == 0 and 1 or math.max(3, (counts[i] / max) * (height - 4))
    table.insert(parts, string.format(
      '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" class="%s"><title>Week %d: %d commit%s</title></rect>',
      (i - 1) * bw + 1, height - h, math.max(bw - 2, 1), h, counts[i] == 0 and "empty" or "full",
      i, counts[i], counts[i] == 1 and "" or "s"))
  end
  table.insert(parts, "</svg>")
  return table.concat(parts)
end

local function worklog_blocks(name)
  if not (quarto and quarto.project and quarto.project.directory) then return nil end
  local path = quarto.project.directory .. "/worklogs/" .. name .. ".json"
  local f = io.open(path, "r")
  if not f then
    error("Work log not found: worklogs/" .. name .. ".json (run scripts/export_worklog.py)")
  end
  local log = pandoc.json.decode(f:read("a"), false)
  f:close()

  local commits = log.commits or {}
  if #commits == 0 then return nil end
  local is_public = log.source == "public" and log.repo

  local files, added, deleted = 0, 0, 0
  local active_days = {}
  for _, c in ipairs(commits) do
    files = files + c.files; added = added + c.added; deleted = deleted + c.deleted
    active_days[c.date:sub(1, 10)] = true
  end
  local n_days = 0
  for _ in pairs(active_days) do n_days = n_days + 1 end
  local first_day = day_number(commits[1].date)
  local n_weeks = math.floor((day_number(commits[#commits].date) - first_day) / 7) + 1

  local h = {}
  local function add(s) table.insert(h, s) end
  add('<div class="worklog">')
  add(string.format(
    '<p class="worklog-summary"><strong>%d commit%s</strong> on %d day%s across %d week%s, %s to %s. ' ..
    '%d file changes, %d lines added, %d removed.</p>',
    #commits, #commits == 1 and "" or "s", n_days, n_days == 1 and "" or "s",
    n_weeks, n_weeks == 1 and "" or "s",
    nice_date(commits[1].date), nice_date(commits[#commits].date),
    math.floor(files), math.floor(added), math.floor(deleted)))
  add(weekly_chart(commits, first_day, n_weeks))

  local rel = log.release
  local rel_index = nil
  if rel and rel.tree then
    for i, c in ipairs(commits) do
      if c.tree == rel.tree then rel_index = i end
    end
  end
  if rel and rel_index then
    local rc = commits[rel_index]
    local repo_name = esc((rel.repo:gsub("^https://github.com/", "")))
    add(string.format(
      '<p class="worklog-release"><strong>Public release:</strong> <a href="%s">%s</a>. ' ..
      'Its contents are identical to tracked commit %d of %d (%s): both have the contents fingerprint ' ..
      '<code title="%s">%s</code>. To check, run <code>git rev-parse HEAD^{tree}</code> in a copy of the public repository.</p>',
      esc(rel.repo), repo_name, rel_index, #commits, nice_date(rc.date),
      esc(rel.tree), esc(rel.tree:sub(1, 10))))
  end
  add(string.format('<details><summary>All %d commits</summary>', #commits))
  add('<table class="worklog-table"><thead><tr><th>Date (UTC)</th><th>Fingerprint</th>' ..
      (is_public and '<th>Message</th>' or '') .. '<th>Files</th><th>Lines</th></tr></thead><tbody>')
  for i = #commits, 1, -1 do
    local c = commits[i]
    local fp = '<code title="' .. esc(c.sha) .. '">' .. esc(c.sha:sub(1, 10)) .. '</code>'
    if is_public then fp = '<a href="' .. esc(log.repo) .. '/commit/' .. esc(c.sha) .. '">' .. fp .. '</a>' end
    if rel_index == i then fp = fp .. ' <span class="worklog-tag">released</span>' end
    add(string.format('<tr><td>%s %s</td><td>%s</td>%s<td>%d</td><td>+%d / −%d</td></tr>',
      esc(c.date:sub(1, 10)), esc(c.date:sub(12, 16)), fp,
      is_public and ('<td>' .. esc(c.message or "") .. '</td>') or "",
      math.floor(c.files), math.floor(c.added), math.floor(c.deleted)))
  end
  add('</tbody></table></details>')
  if is_public then
    add('<p class="worklog-note">From the public repository <a href="' .. esc(log.repo) .. '">' ..
        esc(log.repo:gsub("^https://github.com/", "")) .. '</a>. Each fingerprint links to that commit.</p>')
  else
    add('<p class="worklog-note">From a private repository: dates, sizes and fingerprints only. ' ..
        'Each fingerprint is the commit\'s full hash, so the history can be checked against it ' ..
        'if the repository is made public. <a href="../../worklogs/' .. esc(name) .. '.json">Download the log</a>.</p>')
  end
  add('</div>')

  local blocks = pandoc.Blocks({
    pandoc.Header(2, "Work log", pandoc.Attr("work-log")),
    pandoc.RawBlock("html", table.concat(h, "\n")),
  })

  -- Reflections: public notes, plus fingerprints of the full reflections
  -- (texts appear at release). One list, newest first.
  local items = {}
  for _, n in ipairs(log.notes or {}) do
    table.insert(items, { date = n.date, kind = "note", n = n })
  end
  for _, r in ipairs(log.reflections or {}) do
    table.insert(items, { date = r.date, kind = "refl", r = r })
  end
  table.sort(items, function(a, b)
    if a.date == b.date then return a.kind > b.kind end
    return a.date > b.date
  end)
  local function words(s)
    local lines = {}
    for line in (s .. "\n"):gmatch("(.-)\n") do
      local t = line:gsub("^%s+", ""):gsub("%s+$", "")
      if t ~= "" and not t:match("^#") and not t:match("^<!%-%-") then table.insert(lines, t) end
    end
    return pandoc.Inlines(table.concat(lines, " "))
  end
  local function short(h) return h:sub(1, 12) .. "…" .. h:sub(-4) end
  local function small(inl) return pandoc.Para({ pandoc.Span(inl, pandoc.Attr("", { "reflection-check" })) }) end

  if #items > 0 then
    blocks:insert(pandoc.Header(3, "Reflections", pandoc.Attr("reflections")))
    for _, it in ipairs(items) do
      local head = pandoc.Inlines({ pandoc.Strong(nice_date(it.date .. "T00:00:00Z") .. "."), pandoc.Space() })
      local body = pandoc.Blocks({})
      if it.kind == "note" then
        head:extend(words(it.n.text))
        body:insert(pandoc.Para(head))
      else
        local r = it.r
        local fps = r.fingerprints or {}
        local first = fps[1]
        local when = r.published and nice_date(r.published .. "T00:00:00Z") or ""
        if r.text == nil then
          if log.release or log.source == "public" then
            head:extend(pandoc.Inlines("Reflection written; not released."))
          else
            head:extend(pandoc.Inlines("Reflection written; text published at release."))
          end
          body:insert(pandoc.Para(head))
          if first then
            body:insert(small(pandoc.Inlines({ pandoc.Str("Fingerprint "), pandoc.Code(short(first), pandoc.Attr("", {}, { title = first })),
              pandoc.Str(", published " .. when .. ".") })))
          end
        else
          if r.match == "revised" then head:insert(pandoc.Emph("(revised)")); head:insert(pandoc.Space()) end
          head:extend(words(r.text))
          body:insert(pandoc.Para(head))
          if r.match == "verified" then
            body:insert(small(pandoc.Inlines("✓ Matches the fingerprint published " .. when .. ".")))
          elseif r.match == "revised" then
            if r.original then
              local o = pandoc.Inlines("Original, matching the fingerprint published " .. when .. ": ")
              o:extend(words(r.original))
              body:insert(small(o))
            else
              body:insert(small(pandoc.Inlines("Revised after " .. when .. "; the original version is not available.")))
            end
          else
            body:insert(small(pandoc.Inlines("Written after the last fingerprint was published; no earlier record.")))
          end
        end
      end
      blocks:insert(pandoc.Div(body, pandoc.Attr("", { "reflection" })))
    end
  end
  return blocks
end

function Pandoc(doc)
  local meta = doc.meta
  if not meta.type then return nil end -- not an entry

  local entry_type = str(meta.type)
  local top = pandoc.Blocks({
    pandoc.Div({ pandoc.Plain({ pandoc.Span(entry_type, pandoc.Attr("", { "entry-type" })) }) },
      pandoc.Attr("", { "entry-meta" })),
  })
  -- `ai: pending` (projects still in progress) shows no AI statement yet
  if meta.ai ~= nil and str(meta.ai):lower() ~= "pending" then
    top:insert(ai_box(meta.ai))
  end

  local bottom = pandoc.Blocks({})
  if meta.worklog then
    local wl = worklog_blocks(str(meta.worklog))
    if wl then bottom:extend(wl) end
  end
  local ev = evidence_list(meta.evidence)
  if ev then bottom:extend(ev) end

  local repo = meta["history-repo"] and str(meta["history-repo"]) or ""
  local branch = meta["history-branch"] and str(meta["history-branch"]) or "main"
  local rel = relative_source_path()
  if repo ~= "" and not repo:find("YOUR%-GITHUB%-USERNAME") and rel then
    bottom:insert(pandoc.Div({
      pandoc.Para({
        pandoc.Link("Write-up history", repo .. "/commits/" .. branch .. "/" .. rel),
        pandoc.Str(" · "),
        pandoc.Link("Source", repo .. "/blob/" .. branch .. "/" .. rel),
      })
    }, pandoc.Attr("", { "entry-meta" })))
  end

  local blocks = pandoc.Blocks({})
  blocks:extend(top)
  blocks:extend(doc.blocks)
  blocks:extend(bottom)
  doc.blocks = blocks
  return doc
end
