# Veriforge UI redesign v3 — parity inventory

Status legend: `☑` pending implementation/verification, `☑` verified after the v3 pass. The three columns are intentionally kept stable: **element | old location | new location**.

## Global shell and navigation

| element | old location | new location |
| --- | --- | --- |
| Veriforge mark/name | `components/AppHeader.tsx` | `☑` `components/AppShell.tsx` / `ChatSidebar.tsx` on chat routes; `AppHeader` on non-chat routes |
| Evidence workbench subtitle | `components/AppHeader.tsx` | `☑` `ChatSidebar.tsx` brand block; `AppHeader` on non-chat routes |
| Credit quota loading state | `components/AppHeader.tsx` `QuotaBadge` | `☑` `ChatSidebar.tsx` quota pill; `AppHeader` on non-chat routes |
| Credit quota unavailable state | `components/AppHeader.tsx` `QuotaBadge` | `☑` `ChatSidebar.tsx` quota pill; `AppHeader` on non-chat routes |
| Credit quota button | `components/AppHeader.tsx` `aria-label="Credit quota details"` | `☑` `ChatSidebar.tsx` bottom quota pill; `AppHeader` on non-chat routes |
| Credit quota popover | `components/AppHeader.tsx` dialog | `☑` same `QuotaBadge` component, anchored from sidebar bottom |
| 5h remaining/limit/reset group | `components/AppHeader.tsx` dialog | `☑` same popover content and labels |
| Month remaining/limit/reset group | `components/AppHeader.tsx` dialog | `☑` same popover content and labels |
| `limit reached` state | `components/AppHeader.tsx` dialog | `☑` same popover content and text |
| Theme toggle | `components/ThemeToggle.tsx` | `☑` beside sidebar user row; `AppHeader` on non-chat routes |
| Profile loading state | `components/ProfileMenu.tsx` | `☑` sidebar user row; `AppHeader` on non-chat routes |
| Profile menu trigger | `components/ProfileMenu.tsx` `aria-label="Profile menu"` | `☑` sidebar user row; `AppHeader` on non-chat routes |
| Profile menu dialog | `components/ProfileMenu.tsx` `role="dialog" aria-label="Profile"` | `☑` same dialog, anchored to sidebar user row |
| Admin console item | `components/ProfileMenu.tsx` | `☑` same profile menu item for admins |
| Sign out item | `components/ProfileMenu.tsx` | `☑` same profile menu item |
| App header on non-chat routes | `components/AppShell.tsx` | `☑` retained for sources/admin; dissolved on chat routes |
| Mobile navigation overlay | `ChatSidebar.tsx` | `☑` same close-navigation control, full-height drawer |
| Mobile close navigation | `ChatSidebar.tsx` `aria-label="Close navigation"` | `☑` same aria-label on drawer overlay |
| Mobile close navigation panel | `ChatSidebar.tsx` `aria-label="Close navigation panel"` | `☑` same aria-label on drawer close button |
| Sidebar collapse/expand | `ChatSidebar.tsx` dynamic aria-label | `☑` `ChatSidebar.tsx` rail toggle; same dynamic aria-label/title |
| Rail chat tooltip | `ChatSidebar.tsx` chat `title` | `☑` same title on rail chat buttons |
| Open navigation | `ChatView.tsx` / `ChatIndexPage.tsx` | `☑` main mobile header button; same aria-label |
| Sources route entry | `ChatSidebar.tsx` `aria-label="Sources"` | `☑` primary nav row and existing Sources link |
| Admin route entry | no existing sidebar item | `☑` new conditional primary nav row; ProfileMenu item remains |

## Chat sidebar

| element | old location | new location |
| --- | --- | --- |
| New chat button | `ChatSidebar.tsx` `aria-label="New chat"` | `☑` primary nav row with Plus icon; same aria-label |
| Chats navigation landmark | `ChatSidebar.tsx` `aria-label="Chats"` | `☑` Chats section in sidebar |
| Chat list rows | `ChatSidebar.tsx` | `☑` single-line truncated rows with active surface-raised fill |
| Pinned chat indicator | `ChatSidebar.tsx` Pin icon | `☑` pinned group/row indicator; same data and behavior |
| Chat rename trigger | `ChatSidebar.tsx` `aria-label="Rename <title>"` | `☑` row overflow menu; same aria-label |
| Rename input | `ChatSidebar.tsx` `aria-label="Rename <title>"` | `☑` inline row editor; same aria-label |
| Save rename | `ChatSidebar.tsx` `aria-label="Save rename"` | `☑` inline row editor; same aria-label |
| Pin/unpin action | `ChatSidebar.tsx` dynamic aria-label/aria-pressed | `☑` row overflow menu; same labels and pressed state |
| Delete action | `ChatSidebar.tsx` `aria-label="Delete <title>"` | `☑` row overflow menu; same label and mutation |
| Chat search | no existing control | `☑` new search icon/filter input in sidebar |
| Sources section header | no existing section | `☑` collapsible Sources section with chevron |
| Collection row | `CollectionPicker.tsx` / `ChatSidebar.tsx` new-chat picker | `☑` Sources section row; same collection name/count data |
| No sources state | `CollectionPicker.tsx` / new-chat empty state | `☑` muted `No sources yet` line plus reachable add-source row |
| New-chat collection picker | `ChatSidebar.tsx` currentChatId null | `☑` reachable in new-chat flow; no capability buried |
| Chats section collapse | no existing control | `☑` new section chevron with persisted/guarded state |
| Sources section collapse | no existing control | `☑` new section chevron with persisted/guarded state |

## Composer

| element | old location | new location |
| --- | --- | --- |
| Question textarea | `ChatComposer.tsx` `aria-label="Question"` | `☑` sticky rounded composer; same aria-label and Enter/Shift+Enter behavior |
| Empty-thread placeholder | `ChatComposer.tsx` `Ask a question` | `☑` `Ask anything` when thread is empty |
| Follow-up placeholder | no distinct current placeholder | `☑` `Ask a follow-up` after the first turn |
| Streaming placeholder | `ChatComposer.tsx` `Streaming…` | `☑` same state text |
| Credit-limit placeholder | `ChatComposer.tsx` `Credit limit reached` | `☑` same state text |
| Run settings trigger | `ChatComposer.tsx` `aria-label="Run settings"` | `☑` left toolbar icon with same aria-label/expanded state |
| Run settings popover contents | `ChatComposer.tsx` | `☑` same controls and handlers, repositioned from Plus/Settings trigger |
| Run mode select | `ModePicker.tsx` `aria-label="Run mode"` | `☑` visible Auto/Fast/Deep mode pill; same select and options |
| Model select | `ModelPicker.tsx` `aria-label="Model"` | `☑` visible Model dropdown; same select and options |
| Run source select | `SourcePicker.tsx` `aria-label="Run source"` | `☑` toolbar source select; same select and options |
| Collection picker | `ChatComposer.tsx` / `CollectionPicker.tsx` | `☑` toolbar scope chip and settings popover; same checkbox behavior |
| Selected collection chip | `ChatComposer.tsx` count pill | `☑` removable named collection chip; same collection IDs and remove handler |
| Send button | `ChatComposer.tsx` visible `Send` | `☑` round ArrowUp button; visible/accessible name retained |
| Stop/cancel button | `ChatComposer.tsx` visible `Stop` | `☑` round Square button; visible/accessible name retained |
| Disabled submit state | `ChatComposer.tsx` blocked/streaming logic | `☑` same disabled logic and visible state |
| Composer error alert | `ChatComposer.tsx` `role="alert"` | `☑` muted callout above composer; same error text |
| Composer growth | current textarea rows/resize behavior | `☑` smooth height growth without layout jump |

## Messages and answer surface

| element | old location | new location |
| --- | --- | --- |
| User avatar | `MessageList.tsx` message row | `☑` 24px muted avatar at user bubble top-right |
| Assistant avatar | `MessageList.tsx` message row | `☑` 20px Bot avatar in assistant Answer header |
| User message bubble | `MessageList.tsx` `isAssistant === false` box | `☑` right-aligned surface-raised bubble, max 80%, tail radius |
| Assistant answer label | no explicit label today | `☑` new muted `Answer` label above prose |
| Assistant message prose | `MessageList.tsx` bubble | `☑` unboxed 17px/1.75 Source Serif prose |
| User message text | `MessageList.tsx` pre-wrapped text | `☑` 15px sans pre-wrapped bubble text |
| Markdown headings/bold/list styling | plain text in `MessageList.tsx` | `☑` serif answer typography treatment without changing stored content |
| Streaming caret | `MessageList.tsx` animated accent bar | `☑` muted block caret in prose |
| Verifying hold state | `MessageList.tsx` `role="status"` | `☑` same status and copy in answer slot |
| Searching the web status | `MessageList.tsx` / live status copy | `☑` shimmer status line fed by existing run state |
| Reviewing claims status | live status data | `☑` shimmer status line fed by existing run state |
| Citation chip | `CitationChip.tsx` numbered sup | `☑` rounded inline source pill; same lookup, verdict, tooltip, keyboard focus |
| Citation verdict dot/label | `CitationChip.tsx` tone helpers | `☑` tiny semantic dot plus accessible label |
| Citation hover preview | `CitationChip.tsx` tooltip | `☑` same preview content and positioning logic |
| Citation source-card row | `MessageList.tsx` details cards | `☑` compact hairline cards retained and restyled |
| Live source disclosure | `MessageList.tsx` details `Sources (n)` | `☑` same disclosure and count |
| Sources pill | no existing control | `☑` new stacked-file `N sources` button; opens workspace Sources tab |
| Answer footer metrics | `MessageList.tsx` `AnswerFooter` | `☑` compact metadata row below answer |
| Reviewer revision disclosure | `MessageList.tsx` `RevisionBanner` | `☑` same details summary and diff lines |
| Reviewer diff additions/removals | `MessageList.tsx` `DiffLine` | `☑` same semantic diff colors and copy |
| Abstention status | `MessageList.tsx` `StatusLabel` | `☑` muted answer-slot callout |
| `Try another path` group | `MessageList.tsx` `aria-label="Abstention actions"` | `☑` same group and actions |
| `Searching the web` abstention action | `MessageList.tsx` | `☑` same action and handler |
| `Deep mode` abstention action | `MessageList.tsx` | `☑` same action and handler |
| Suggestions label | `MessageList.tsx` `Suggested follow-ups:` | `☑` `Related` label |
| Suggestion buttons | `MessageList.tsx` suggestion buttons | `☑` full-width hairline rows with CornerDownRight; same submit callback |
| Suggestion list semantics | `MessageList.tsx` `role=list/listitem` | `☑` same roles |
| Web-search error copy | `ChatView.tsx` `runFailureMessage` | `☑` muted answer-slot callout, same strings |
| Connection-lost resume | `ChatView.tsx` button | `☑` same resume button and label |
| Chat-not-found state | `ChatView.tsx` | `☑` same text in calm empty/error slot |
| Empty conversation state | `MessageList.tsx` `Ask anything to start the conversation.` | `☑` centred muted empty state; same required text |
| Workspace-ready supporting copy | `MessageList.tsx` | `☑` same supporting copy |
| Copy action | no existing API action | `☑` new client-side icon action; no backend dependency |
| Link-to-message action | no existing API action | `☑` new client-side icon action; no backend dependency |
| Thumbs-up action | no existing API | `☑` omit unless an existing API appears; no fake mutation |
| Thumbs-down action | no existing API | `☑` omit unless an existing API appears; no fake mutation |
| Regenerate action | no existing API | `☑` omit unless an existing API appears; no fake mutation |
| Answer overflow action | no existing API | `☑` new client-side menu placeholder only if it exposes existing actions |
| Scroll-to-bottom control | no existing control | `☑` floating ArrowDown button above composer; client-side only |

## Trace / sources / metrics workspace

| element | old location | new location |
| --- | --- | --- |
| Trace panel landmark | `TracePanel.tsx` aside | `☑` right workspace panel, collapsible/expandable |
| Trace tab | `TracePanel.tsx` `Trace` | `☑` ListTree tab with text and count; keyboard tablist semantics |
| Sources tab | `TracePanel.tsx` `Sources (n)` | `☑` Quote tab with text and count; same count data |
| Metrics tab | `TracePanel.tsx` `Metrics` | `☑` Gauge tab with text; same tab |
| Live indicator | `TracePanel.tsx` `live` | `☑` workspace header live dot/text |
| Panel expand toggle | no existing control | `☑` Maximize2 control, approximately 50% width on desktop |
| Panel collapse toggle | no existing control | `☑` PanelRight control, same panel state persistence |
| Thinking disclosure | `TracePanel.tsx` | `☑` compact trace disclosure with same text |
| Steps rows | `TracePanel.tsx` `StepRow` | `☑` vertical trace list with duration values |
| Decision timeline rows | `DecisionTimeline.tsx` | `☑` vertical list with connector lines and same data |
| Decision stage labels | `DecisionTimeline.tsx` / `decisionMeta.ts` | `☑` same labels |
| Decision outcome labels | `DecisionTimeline.tsx` | `☑` same semantic shape/text |
| Decision probability meter | `DecisionTimeline.tsx` | `☑` same meter and threshold values |
| Decision reasoning disclosure | `DecisionTimeline.tsx` | `☑` same reasoning text/control |
| Jev badge | `DecisionTimeline.tsx` | `☑` mono Jev badge |
| Fallback badge | `DecisionTimeline.tsx` | `☑` mono fallback badge |
| Jev-fallback tooltip | `DecisionTimeline.tsx` `title` | `☑` same title/tooltip meaning |
| Sources query context line | no current query prop | `☑` new muted `Results for '<query…>'` line where query is available |
| Source item name | `SourcesTab.tsx` | `☑` source list row |
| Source item excerpt | `SourcesTab.tsx` | `☑` 3-line clamped snippet |
| Source item page ref | `SourcesTab.tsx` | `☑` page reference metadata |
| Source item scores | `SourcesTab.tsx` vec/bm25/fused/rerank | `☑` same scores in compact mono metadata |
| Source item verdict | `CitationChip.tsx` / source data where available | `☑` supported/partial/unsupported badge/dot |
| DocumentViewer source click | current `SourcesTab` is display-only; viewer exists on Sources page | `☑` source row remains interactive when a document callback is supplied; chat workspace routes to the existing Sources page/viewer flow |
| Sources empty state | `SourcesTab.tsx` | `☑` centred two-line muted state |
| Metrics empty state | `TracePanel.tsx` `Metrics land when the run completes.` | `☑` same text and state |
| Metrics stat tiles | current answer scores/usage rows | `☑` latency, tokens, credits, faithfulness, hops; preserve all existing values |
| Latency waterfall | `TracePanel.tsx` `WaterfallRow` | `☑` same rows and values in a compact chart |
| Usage section | `TracePanel.tsx` | `☑` same tokens, credits, context values |
| Hold/reviewer status | `TracePanel.tsx` | `☑` same warning status and copy |

## Sources page

| element | old location | new location |
| --- | --- | --- |
| Sources page mobile open | `SourcesPage.tsx` `aria-label="Open source navigation"` | `☑` same aria-label in mobile header |
| Sources page mobile close | `CollectionList.tsx` `aria-label="Close source navigation"` | `☑` same aria-label on overlay |
| Sources page mobile panel close | `CollectionList.tsx` `aria-label="Close source navigation panel"` | `☑` same aria-label on close button |
| Sources collection list | `CollectionList.tsx` `aria-label="Collections"` | `☑` sidebar collection rows |
| Select collection | `CollectionList.tsx` | `☑` collection row; same selection handler |
| Collection name | `CollectionList.tsx` | `☑` row name |
| Shared collection marker | `CollectionList.tsx` | `☑` same `(shared)` marker |
| Collection document count | `CollectionList.tsx` | `☑` same count |
| No collections state | `CollectionList.tsx` | `☑` same state plus quiet new-source action |
| Create collection input | `CollectionList.tsx` | `☑` create row/input |
| Create collection action | `CollectionList.tsx` | `☑` same action and mutation |
| Chats link from Sources | `CollectionList.tsx` | `☑` bottom sidebar nav row |
| New source card/action | no current card | `☑` `+ New source` card/row; same create flow |
| Selected collection header | `SourcesPage.tsx` | `☑` detail header |
| Shared badge | `SourcesPage.tsx` | `☑` same shared badge |
| Document count/updated metadata | `SourcesPage.tsx` | `☑` same metadata |
| Document list empty state | `DocumentList.tsx` | `☑` same empty-state text |
| Document name/view action | `DocumentList.tsx` | `☑` document table row |
| Document status | `DocumentList.tsx` `StatusChip` | `☑` status badge |
| Page quality flags | `DocumentList.tsx` | `☑` same flags and tooltip/summary text |
| Document tags | `DocumentList.tsx` | `☑` same tags |
| Re-index document | `DocumentList.tsx` | `☑` row action |
| Delete document | `DocumentList.tsx` | `☑` row action and confirmation |
| Upload dropzone | `UploadDropzone.tsx` | `☑` dropzone card |
| Upload file input | `UploadDropzone.tsx` | `☑` hidden native input behind dropzone |
| Upload copy/limits | `UploadDropzone.tsx` | `☑` same text |
| Upload outcome rows | `UploadDropzone.tsx` | `☑` same uploading/queued/error states |
| Document viewer | `DocumentViewer.tsx` | `☑` right detail drawer |
| Document viewer close | `DocumentViewer.tsx` | `☑` same close control |
| Document viewer re-index | `DocumentViewer.tsx` | `☑` same action |
| Page flags in viewer | `DocumentViewer.tsx` | `☑` same flags |
| Chunk groups/content | `DocumentViewer.tsx` | `☑` same content |
| Tag list | `DocumentViewer.tsx` | `☑` same tag chips |
| Add tag input | `DocumentViewer.tsx` `aria-label="Add tag"` | `☑` same aria-label and Enter behavior |
| Remove tag | `DocumentViewer.tsx` `aria-label="Remove tag <tag>"` | `☑` same aria-label and behavior |
| Save tags | `DocumentViewer.tsx` `Save tags` | `☑` same action and loading state |
| Starter questions | `StarterQuestions.tsx` | `☑` same question data; quiet chip row |

## Admin

| element | old location | new location |
| --- | --- | --- |
| Admin loading state | `AdminPage.tsx` | `☑` same text in calm page state |
| Administrator access state | `AdminPage.tsx` | `☑` same text in calm page state |
| Admin shell header | `AdminPage.tsx` | `☑` quiet hairline table shell |
| Admin sections nav | `AdminPage.tsx` `aria-label="Admin sections"` | `☑` same eight section buttons and labels |
| Decision layer section | `AdminPage.tsx` | `☑` same section |
| Runtime settings section | `AdminPage.tsx` | `☑` same section |
| Providers section | `AdminPage.tsx` | `☑` same section |
| Models section | `AdminPage.tsx` | `☑` same section |
| Model roles section | `AdminPage.tsx` | `☑` same section |
| Plans/quota overrides section | `AdminPage.tsx` | `☑` same section |
| Users section | `AdminPage.tsx` | `☑` same section |
| Audit log section | `AdminPage.tsx` | `☑` same section |
| Runtime settings fields | `AdminPage.tsx` | `☑` same fields/selects/validation |
| Runtime settings Save | `AdminPage.tsx` | `☑` same action and notice |
| Provider Add/Test/Save actions | `AdminPage.tsx` | `☑` same actions and labels |
| Model Add/Save/Activate actions | `AdminPage.tsx` | `☑` same actions and labels |
| Model role Save action | `AdminPage.tsx` | `☑` same action |
| Plan Add/Save actions | `AdminPage.tsx` | `☑` same actions |
| Versions/rollback Activate action | `AdminPage.tsx` | `☑` same action |
| Audit rows | `AdminPage.tsx` | `☑` same data table |
| User 5h override input | `AdminPage.tsx` dynamic aria-label | `☑` same dynamic aria-label |
| User monthly override input | `AdminPage.tsx` dynamic aria-label | `☑` same dynamic aria-label |
| User Save quota | `AdminPage.tsx` | `☑` same action |
| User role select | `AdminPage.tsx` dynamic aria-label | `☑` same dynamic aria-label/options |
| User Enable/Disable | `AdminPage.tsx` | `☑` same action |
| Plan monthly credits input | `AdminPage.tsx` dynamic aria-label | `☑` same dynamic aria-label |
| Plan Save | `AdminPage.tsx` | `☑` same action |
| Decision stats window select | `DecisionLayerPanel.tsx` `aria-label="Decision stats window"` | `☑` same aria-label/options |
| Decision stat tiles | `DecisionLayerPanel.tsx` | `☑` same labels/values/pass states |
| Circuit breaker status | `DecisionLayerPanel.tsx` | `☑` same state/cooldown text |
| Decision events empty state | `DecisionLayerPanel.tsx` | `☑` same text |
| Disagreement empty state | `DecisionLayerPanel.tsx` | `☑` same text |
| Jev/fallback disagreement data | `DecisionLayerPanel.tsx` | `☑` same rows and metadata |

## Auth

| element | old location | new location |
| --- | --- | --- |
| Veriforge auth mark | `AuthShell.tsx` | `☑` 400px centred auth card |
| Auth theme toggle | `AuthShell.tsx` | `☑` card top-right |
| Login email field | `LoginPage.tsx` `aria-label="Email"` | `☑` same field/label/validation |
| Login password field | `LoginPage.tsx` `aria-label="Password"` | `☑` same field/label/validation |
| Login submit | `LoginPage.tsx` `Sign in` | `☑` primary button, same handler |
| Login error | `LoginPage.tsx` `role="alert"` | `☑` same error slot/copy |
| Login create-account link | `LoginPage.tsx` | `☑` same link |
| Login forgot-password link | `LoginPage.tsx` | `☑` same link |
| Signup email field | `SignupPage.tsx` `aria-label="Email"` | `☑` same field/label/validation |
| Signup password field | `SignupPage.tsx` `aria-label="Password"` | `☑` same field/label/validation |
| Signup submit | `SignupPage.tsx` `Sign up` | `☑` primary button, same handler |
| Signup error | `SignupPage.tsx` `role="alert"` | `☑` same error slot/copy |
| Signup login link | `SignupPage.tsx` | `☑` same link |
| Forgot-password email field | `ForgotPasswordPage.tsx` `aria-label="Email"` | `☑` same field/label/validation |
| Forgot-password submit | `ForgotPasswordPage.tsx` `Send reset link` | `☑` same action |
| Forgot-password sent state | `ForgotPasswordPage.tsx` | `☑` same success copy |
| Forgot-password back link | `ForgotPasswordPage.tsx` | `☑` same link |
| Reset-password field | `ResetPasswordPage.tsx` `aria-label="New password"` | `☑` same field/label/min length |
| Reset-password submit | `ResetPasswordPage.tsx` | `☑` same action |
| Reset-password error | `ResetPasswordPage.tsx` `role="alert"` | `☑` same error/copy |
| Reset-password back link | `ResetPasswordPage.tsx` | `☑` same link |
| OAuth callback status | `OAuthCallbackPage.tsx` | `☑` same `Signing you in` / `One moment…` state |
| Auth secure-access label | `AuthShell.tsx` | `☑` same `Secure access` copy |

## Selector and contract notes

- No current `data-testid` attributes were found in the inspected `.tsx` source; existing Playwright selectors are primarily role/name based.
- Existing `aria-label`, `role`, `aria-expanded`, `aria-pressed`, and visible button names listed above must remain unchanged unless a selector is deliberately re-pointed in the commit body.
- Backend contracts, generated SDK/types, query keys, Zustand state, routes, and validation remain unchanged.
- Verification completed: 20/20 local Playwright e2e tests, 21/21 unit tests, build, lint, and real-browser screenshots at 1440px, 1100px, and 390px.
- The decision-layer e2e setup now normalizes the explicit dark default before its light/dark screenshot assertions; no assertion was removed or weakened.
- Workspace source rows retain the existing source data and route users to the existing Sources page/viewer flow; no API or schema work was added.
- Metrics uses `Stages` rather than inventing a hop count because the existing `Metrics` contract has no hop field.
- Final verification must tick every row and run the existing unit/e2e suites without deleting or weakening assertions.

## v3.1 verification addendum

| element | old location | new location |
| --- | --- | --- |
| Account quota/profile/theme controls | `AppHeader.tsx` + `ChatSidebar.tsx` | shared `ProfileMenu` account trigger; quota pill retained |
| Composer mode/model/source controls | native `<select>` elements | Radix `Select` triggers in `ChatComposer` |
| Citation evidence | positioned tooltip in `CitationChip.tsx` | Radix `HoverCard` with number-only marker |
| Composer separator | `ChatComposer.tsx` borders | 24px main-to-transparent fade |
| Live run feedback | status line only | optimistic user turn + `Working` step block |
| Sources tab | all retrieved chunks | cited group plus collapsed also-retrieved group |
| Icon-only controls | ad-hoc button classes | shared `IconButton` sizes 28/32 |
| Colour tokens | v3 cool-negre palette | v3.1 warm-neutral tokens in `tokens.css` |

All rows above were exercised by the local Playwright suite (20/20 passing) after selector updates for portalled Radix content. The existing parity rows remain unchanged.
