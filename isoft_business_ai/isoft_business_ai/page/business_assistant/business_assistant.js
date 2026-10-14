// Full workspace for the assistant.
//
// A collapsible history rail, one readable column for the conversation, and a
// composer pinned to the bottom. Rendering is shared with the quick panel
// through isoft_business_ai.* so a table, a figure or a document link looks
// identical in both places.
//
// Deliberately absent: a stop button, token streaming and attachments. `ask`
// is one blocking call that reports its tools only when it is done, so those
// controls would be decoration.

frappe.pages['business-assistant'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('ISOFT Business Assistant'),
		single_column: true,
	});
	frappe.pages['business-assistant'].instance = new BusinessAIPage(page);
};

frappe.pages['business-assistant'].on_page_show = function () {
	// Frappe already supports a full-bleed body; this page wants every pixel.
	$(document.body).addClass('full-width ibai-fullpage');
	const inst = frappe.pages['business-assistant'].instance;
	if (inst) inst.loadHistory();
};

// on_page_hide never fires in v13 and routing raises no hashchange, so the
// body classes have to be cleaned up from the route change itself.
$(document).on('page-change', function () {
	const route = (frappe.get_route() || [])[0];
	if (route !== 'business-assistant') {
		$(document.body).removeClass('full-width ibai-fullpage');
	}
});

class BusinessAIPage {
	constructor(page) {
		this.page = page;
		this.conversation = null;
		this.title = null;
		this.busy = false;
		this.composing = false;
		this.lastQuestion = '';
		this.mentioned = new Set();

		this.render();
		this.bind();
		this.notice();
		this.loadHistory();
	}

	/* ------------------------------------------------------------- markup */

	render() {
		const ico = isoft_business_ai.icon;

		this.page.main.html(
			'<div class="ibai-console">' +
				'<aside class="ibai-rail">' +
					'<div class="ibai-brand">' +
						'<span class="ibai-brand-mark">' + isoft_business_ai.galaxy(22) + '</span>' +
						'<span class="ibai-brand-name">' + __('ISOFT Business Assistant') + '</span>' +
					'</div>' +
					'<div class="ibai-rail-top">' +
						'<button class="ibai-new">' +
							ico('<path d="M12 5v14M5 12h14"/>', 15) +
							'<span>' + __('New conversation') + '</span>' +
						'</button>' +
					'</div>' +
					'<div class="ibai-search">' +
						'<input type="search" autocomplete="off" ' +
							'placeholder="' + __('Search conversations') + '">' +
					'</div>' +
					'<div class="ibai-hlist"></div>' +
				'</aside>' +

				'<main class="ibai-main">' +
					'<div class="ibai-main-top">' +
						'<button class="ibai-ico ibai-rail-toggle" aria-label="' + __('Toggle history') + '" ' +
							'title="' + __('Toggle history') + '">' +
							ico('<path d="M3 6h18M3 12h18M3 18h18"/>') + '</button>' +
						'<a class="ibai-ico ibai-back" href="/app" aria-label="' + __('Back to ERP') + '" ' +
							'title="' + __('Back to ERP') + '">' +
							ico('<path d="M3 11.5 12 4l9 7.5M5.5 9.8V20h13V9.8"/>') + '</a>' +
						'<div class="ibai-main-title">' + __('New conversation') + '</div>' +
						'<span class="ibai-scope" hidden></span>' +
						'<button class="ibai-ico ibai-act-tools" aria-label="' + __('What can I ask?') + '" ' +
							'title="' + __('What can I ask?') + '">' +
							ico('<circle cx="12" cy="12" r="9"/><path d="M9.2 9.3a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.2-2.8 4"/><circle cx="12" cy="17.6" r=".6" fill="currentColor"/>') +
						'</button>' +
						'<button class="ibai-ico ibai-act-new" aria-label="' + __('New conversation') + '" ' +
							'title="' + __('New conversation') + '">' +
							ico('<path d="M12 5v14M5 12h14"/>') + '</button>' +
					'</div>' +

					'<div class="ibai-body">' +
						'<div class="ibai-stream" tabindex="0"></div>' +
						'<button class="ibai-jump" hidden>' +
							ico('<path d="M12 5v14M19 12l-7 7-7-7"/>', 12) +
							'<span>' + __('Jump to latest') + '</span></button>' +
					'</div>' +

					'<div class="ibai-composer">' +
						'<div class="ibai-field">' +
							'<textarea class="ibai-input" rows="1" aria-label="' + __('Message') + '" ' +
								'placeholder="' + __('Ask about sales, customers, debt, purchases or stock…') + '"></textarea>' +
							'<button class="ibai-send" aria-label="' + __('Send') + '" disabled>' +
								ico('<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/>', 16) + '</button>' +
						'</div>' +
						'<div class="ibai-foot">' +
							'<span class="ibai-hint">' + __(
								'Answers come from verified queries on your own data, within your permissions. This assistant reads only; it changes nothing.'
							) + '</span>' +
							'<button class="ibai-mute" aria-label="' + __('Sound') + '"></button>' +
						'</div>' +
					'</div>' +
				'</main>' +
			'</div>'
		);

		this.$console = this.page.main.find('.ibai-console');
		this.$stream = this.page.main.find('.ibai-stream');
		this.$input = this.page.main.find('.ibai-input');
		this.$send = this.page.main.find('.ibai-send');
		this.$hlist = this.page.main.find('.ibai-hlist');
		this.$search = this.page.main.find('.ibai-search input');
		this.$title = this.page.main.find('.ibai-main-title');
		this.$scope = this.page.main.find('.ibai-scope');
		this.$mute = this.page.main.find('.ibai-mute');
		this.$jump = this.page.main.find('.ibai-jump');

		this.scroll = isoft_business_ai.scroller(this.$stream, this.$jump);
		this.restoreRail();
		this.drawMute();
		this.welcome();
	}

	/* ------------------------------------------------------------- events */

	bind() {
		const $composer = this.page.main.find('.ibai-composer');
		isoft_business_ai.attachMentions(this.$input, $composer);
		// After attachMentions, so the @ menu gets first refusal on a keystroke.
		isoft_business_ai.typeahead(this.$input, $composer, text => {
			this.$input.val(text);
			this.sizeInput();
			this.send();
		});
		isoft_business_ai.fitPlaceholder(this.$input,
			__('Ask about sales, customers, debt, purchases or stock…'),
			__('Ask a question…'));

		this.$send.on('click', () => this.send());
		this.page.main.find('.ibai-new, .ibai-act-new').on('click', () => this.newConversation());
		this.page.main.find('.ibai-rail-toggle').on('click', () => this.rail());
		this.page.main.find('.ibai-act-tools').on('click', () => this.showTools());
		this.$mute.on('click', () => {
			const on = !isoft_business_ai.sound.enabled();
			isoft_business_ai.sound.setEnabled(on);
			this.drawMute();
			if (on) isoft_business_ai.sound.received();
		});

		this.$input.on('compositionstart', () => { this.composing = true; });
		this.$input.on('compositionend', () => { this.composing = false; });
		this.$input.on('keydown', e => {
			if (e.key !== 'Enter' || e.shiftKey) return;
			if (this.composing || e.isComposing || e.keyCode === 229) return;
			e.preventDefault();
			this.send();
		});
		this.$input.on('input', () => this.sizeInput());

		let debounce = null;
		this.$search.on('input', () => {
			clearTimeout(debounce);
			debounce = setTimeout(() => this.loadHistory(), 220);
		});

		// Ctrl/Cmd+K focuses the composer, the one shortcut worth having here.
		this.page.main.on('keydown', e => {
			if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
				e.preventDefault();
				this.$input.focus();
			}
		});

		setTimeout(() => this.$input.focus(), 120);
	}

	sizeInput() {
		const el = this.$input[0];
		el.style.height = 'auto';
		el.style.height = Math.max(36, Math.min(el.scrollHeight, 190)) + 'px';
		this.$send.prop('disabled', !(this.$input.val() || '').trim() || this.busy);
	}

	drawMute() {
		const on = isoft_business_ai.sound.enabled();
		const ico = isoft_business_ai.icon;
		this.$mute
			.attr('aria-pressed', on ? 'true' : 'false')
			.attr('title', on ? __('Sound on') : __('Sound off'))
			.html(on
				? ico('<path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>', 13)
				: ico('<path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M22 9l-6 6M16 9l6 6"/>', 13));
	}

	/* ---------------------------------------------------------------- rail */

	restoreRail() {
		let collapsed = window.innerWidth < 900;
		try {
			const saved = localStorage.getItem('ibai_rail');
			if (saved !== null) collapsed = saved === '0';
		} catch (e) {
			// Blocked storage: fall back to the width-based default.
		}
		this.$console.toggleClass('rail-collapsed', collapsed);
		this.page.main.find('.ibai-rail-toggle').attr('aria-expanded', collapsed ? 'false' : 'true');
	}

	rail(force) {
		const show = force === undefined
			? this.$console.hasClass('rail-collapsed')
			: force;
		this.$console.toggleClass('rail-collapsed', !show);
		this.page.main.find('.ibai-rail-toggle').attr('aria-expanded', show ? 'true' : 'false');
		try { localStorage.setItem('ibai_rail', show ? '1' : '0'); } catch (e) { /* ignore */ }
		if (show) setTimeout(() => this.$search.focus(), 80);
	}

	/* ------------------------------------------------------------- notices */

	notice() {
		if (isoft_business_ai.is_enabled() && isoft_business_ai.is_configured()) return;
		const message = !isoft_business_ai.is_enabled()
			? __('The assistant is turned off, so new questions will not be answered.')
			: __('No API key is configured in site_config.json, so new questions will not be answered.');
		const $bar = $('<div class="ibai-notice"></div>').text(message);
		if (isoft_business_ai.flags().is_manager) {
			$bar.append($('<a href="#"></a>').text(' ' + __('Open settings')).on('click', e => {
				e.preventDefault();
				frappe.set_route('Form', 'Isoft Business AI Settings');
			}));
		}
		this.$stream.prepend($bar);
	}

	/* ------------------------------------------------------------- history */

	loadHistory() {
		const term = (this.$search.val() || '').trim();
		frappe.call({
			method: 'isoft_business_ai.api.list_conversations',
			args: { limit: 60, search: term || undefined },
			callback: r => {
				const rows = r.message || [];
				this.$hlist.empty();
				if (!rows.length) {
					this.$hlist.html('<div class="ibai-empty">' +
						(term ? __('Nothing matches that.') : __('No conversations yet.')) + '</div>');
					return;
				}
				let group = null;
				rows.forEach(c => {
					const g = isoft_business_ai.dateGroup(c.modified);
					if (g !== group) {
						group = g;
						$('<div class="ibai-hgroup"></div>').text(g).appendTo(this.$hlist);
					}
					this.$hlist.append(this.historyRow(c));
				});
			},
		});
	}

	historyRow(c) {
		const title = isoft_business_ai.stripMentions(c.title);
		const $row = $('<div class="ibai-hrow" role="button" tabindex="0"></div>')
			.toggleClass('active', c.name === this.conversation);
		const $main = $('<div class="ibai-hrow-main"></div>');
		$('<div class="ibai-hrow-t"></div>').text(title).attr('title', title).appendTo($main);
		$('<div class="ibai-hrow-w"></div>')
			.text(isoft_business_ai.when(c.modified)).appendTo($main);
		$row.append($main);

		const open = () => this.openConversation(c.name, title);
		$main.on('click', open);
		$row.on('keydown', e => {
			if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
		});

		$('<button class="ibai-hrow-menu" aria-label="' + __('Conversation options') + '"></button>')
			.html(isoft_business_ai.icon('<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>', 14))
			.on('click', e => {
				e.stopPropagation();
				isoft_business_ai.rowMenu($(e.currentTarget), [
					{ label: __('Rename'), run: () => this.rename(c, title) },
					{ label: __('Delete'), danger: true, run: () => this.remove(c, title) },
				]);
			})
			.appendTo($row);
		return $row;
	}

	rename(c, current) {
		const d = new frappe.ui.Dialog({
			title: __('Rename conversation'),
			fields: [{ fieldname: 'title', fieldtype: 'Data', label: __('Title'),
				default: current, reqd: 1 }],
			primary_action_label: __('Save'),
			primary_action: values => {
				d.hide();
				frappe.call({
					method: 'isoft_business_ai.api.rename_conversation',
					args: { name: c.name, title: values.title },
					callback: () => {
						if (this.conversation === c.name) this.setTitle(values.title);
						this.loadHistory();
					},
				});
			},
		});
		d.show();
	}

	remove(c, title) {
		frappe.warn(
			__('Delete this conversation?'),
			isoft_business_ai.esc(title),
			() => frappe.call({
				method: 'isoft_business_ai.api.delete_conversation',
				args: { name: c.name },
				callback: () => {
					if (this.conversation === c.name) this.newConversation();
					else this.loadHistory();
				},
			}),
			__('Delete'),
			true
		);
	}

	openConversation(name, title) {
		frappe.call({
			method: 'isoft_business_ai.api.get_conversation',
			args: { name },
			callback: r => {
				if (!r.message) return;
				this.conversation = name;
				this.mentioned.clear();
				this.setTitle(title || isoft_business_ai.stripMentions(r.message.title));
				this.$stream.empty();
				(r.message.messages || []).forEach(m => {
					if (m.role === 'user') {
						isoft_business_ai.extractMentions(m.content)
							.forEach(k => this.mentioned.add(k));
						this.addUser(m.content, m.creation);
					} else {
						this.addAnswer({ answer: m.content, results: m.results || [],
							message: m.name }, null, m.creation);
					}
				});
				this.$hlist.find('.ibai-hrow').removeClass('active');
				this.loadHistory();
				this.scroll.toBottom(true);
				if (window.innerWidth < 900) this.rail(false);
			},
		});
	}

	setTitle(title) {
		this.title = title || null;
		this.$title.text(title || __('New conversation')).attr('title', title || '');
	}

	/* --------------------------------------------------------- empty state */

	welcome() {
		this.$stream.html(
			'<div class="ibai-welcome">' +
				'<div class="ibai-welcome-title">' + __('How can I help with your ERP?') + '</div>' +
				'<div class="ibai-welcome-sub"></div>' +
				'<div class="ibai-starters"></div>' +
			'</div>'
		);
		this.loadBriefing();
	}

	/**
	 * Opens on the manager's position rather than a generic prompt list. Runs no
	 * model: the same permission-aware queries the tools use, so it is instant
	 * and free, and its figures match what the assistant would quote.
	 */
	/**
	 * Three suggestions and a company line — nothing more. Where you stand is
	 * still here, one click away, rather than six cards deep on every open.
	 */
	loadBriefing() {
		frappe.call({
			method: 'isoft_business_ai.api.briefing',
			callback: r => {
				const $w = this.$stream.find('.ibai-welcome');
				if (!$w.length) return;
				const d = r.message || {};
				const targets = d.targets || [];
				const alerts = d.alerts || [];
				isoft_business_ai.setSuggestions(d.suggestions);

				if (d.company) {
					$w.find('.ibai-welcome-sub').text(d.company);
					this.$scope.prop('hidden', false).html(
						'<span class="ibai-context-chip"><span class="dt">' +
						isoft_business_ai.esc(__('Company')) + '</span><span class="nm">' +
						isoft_business_ai.esc(d.company) + '</span></span>');
				}

				// Deliberately NOT the alert asks: those name a real customer
				// ("Show the statement for <a named customer>"), which is no way to
				// greet whoever opens the assistant. The opening stays general;
				// the alerts are still one question away via business_alerts.
				this.starters($w.find('.ibai-starters'), null);
			},
			error: () => this.starters(this.$stream.find('.ibai-starters')),
		});
	}

	/**
	 * Falls back to the catalogue of what the tools can answer, so the opening
	 * never offers a question the assistant has no way to reach.
	 */
	starters($host) {
		isoft_business_ai.loadSuggestions(all => {
			$host.empty();
			isoft_business_ai.openingSuggestions(all).forEach(q => {
				$('<button class="ibai-starter"></button>').text(q)
					.on('click', () => { this.$input.val(q); this.sizeInput(); this.send(); })
					.appendTo($host);
			});
		});
	}

	newConversation() {
		this.conversation = null;
		this.mentioned.clear();
		this.setTitle(null);
		this.welcome();
		this.notice();
		this.$hlist.find('.ibai-hrow').removeClass('active');
		this.$input.val('');
		this.sizeInput();
		this.$input.focus();
		this.loadHistory();
	}

	/* ---------------------------------------------------------------- send */

	send(retryText) {
		if (this.busy) return;
		const question = retryText !== undefined ? retryText : (this.$input.val() || '').trim();
		if (!question) return;

		isoft_business_ai.extractMentions(question).forEach(k => this.mentioned.add(k));
		this.lastQuestion = question;

		if (retryText === undefined) { this.$input.val(''); this.sizeInput(); }
		this.$stream.find('.ibai-welcome, .ibai-fail-turn').remove();
		this.addUser(question);
		isoft_business_ai.sound.sent();

		this.busy = true;
		this.$send.prop('disabled', true);
		const $working = this.addWorking();

		frappe.call({
			method: 'isoft_business_ai.api.ask',
			args: { question, conversation: this.conversation },
			callback: r => {
				$working.remove();
				this.busy = false;
				this.sizeInput();
				if (!r.message) return this.addFailure();
				this.conversation = r.message.conversation;
				this.addAnswer(r.message, r.message.usage);
				isoft_business_ai.sound.received();
				if (!this.title) this.setTitle(isoft_business_ai.stripMentions(question));
				this.loadHistory();
			},
			error: () => {
				$working.remove();
				this.busy = false;
				this.sizeInput();
				this.addFailure();
				isoft_business_ai.sound.error();
			},
			// v13 can call neither callback on some failures; always() settles it.
			always: () => {
				if (!this.busy) return;
				$working.remove();
				this.busy = false;
				this.sizeInput();
				this.addFailure();
			},
		});
	}

	/* ------------------------------------------------------------ messages */

	addUser(text, when) {
		const $turn = $('<div class="ibai-turn ibai-turn-user"></div>');
		const $wrap = $('<div></div>');
		$('<div class="ibai-bubble"></div>')
			.html(isoft_business_ai.format_text(text)).appendTo($wrap);
		if (when) {
			$('<div class="ibai-when"></div>')
				.text(isoft_business_ai.when(when)).appendTo($wrap);
		}
		$turn.append($wrap).appendTo(this.$stream);
		this.scroll.toBottom();
	}

	addWorking() {
		const $turn = $('<div class="ibai-turn ibai-turn-bot"></div>').html(
			'<span class="ibai-working"><span class="ibai-dots">' +
			'<span class="ibai-dot"></span><span class="ibai-dot"></span><span class="ibai-dot"></span>' +
			'</span>' + __('Working on it') + '</span>'
		);
		this.$stream.append($turn);
		this.scroll.toBottom();
		return $turn;
	}

	/** Keeps the question so a retry costs nothing but a click. */
	addFailure(message) {
		const $turn = $('<div class="ibai-turn ibai-turn-bot ibai-fail-turn"></div>');
		const $box = $('<div class="ibai-fail"></div>');
		const $text = $('<div class="ibai-fail-text"></div>');
		$('<b></b>').text(__('That did not go through')).appendTo($text);
		$('<span></span>').text(message ||
			__('The assistant could not be reached. Your question has been kept.')).appendTo($text);
		$box.append($text);
		$('<button class="ibai-retry"></button>').text(__('Retry'))
			.on('click', () => {
				$turn.remove();
				this.send(this.lastQuestion);
			}).appendTo($box);
		$turn.append($box).appendTo(this.$stream);
		this.scroll.follow();
	}

	addAnswer(payload, usage, when) {
		const $turn = $('<div class="ibai-turn ibai-turn-bot"></div>');

		if ((payload.results || []).length) {
			$turn.append(isoft_business_ai.render_steps(payload.results));
		}
		const $answer = $('<div class="ibai-answer"></div>')
			.html(isoft_business_ai.format_text(payload.answer));
		$turn.append($answer);

		// The workspace is wide enough to let a many-column table break out of
		// the reading column instead of scrolling it sideways.
		(payload.results || []).forEach((res, i) => {
			$turn.append(isoft_business_ai.render_result(res, {
				message_name: payload.message, index: i, wide: true,
			}));
		});

		const $tools = $('<div class="ibai-turn-tools"></div>');
		const $copy = $('<button class="ibai-tool"></button>')
			.html(isoft_business_ai.icon('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', 12) +
				'<span>' + __('Copy answer') + '</span>')
			.on('click', () => isoft_business_ai.copy(payload.answer || '', $copy, $answer));
		$tools.append($copy);

		// Only offered where there is a stored answer to attach it to.
		if (payload.message) {
			const $flag = $('<button class="ibai-tool ibai-flag"></button>')
				.html(isoft_business_ai.icon('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>', 12) +
					'<span>' + __('Report') + '</span>')
				.attr('title', __('Report this answer as wrong'))
				.on('click', () => isoft_business_ai.reportAnswer(payload.message, $flag));
			$tools.append($flag);
		}

		$turn.append($tools);

		if (usage) {
			$('<div class="ibai-source"></div>').text(
				usage.input_tokens + ' ' + __('input tokens') + ' (' +
				(usage.cache_read_input_tokens || 0) + ' ' + __('cached') + ') · ' +
				usage.output_tokens + ' ' + __('output')).appendTo($turn);
		}
		if (when) {
			$('<div class="ibai-when"></div>')
				.text(isoft_business_ai.when(when)).appendTo($turn);
		}
		$turn.appendTo(this.$stream);
		this.scroll.follow();
	}

	/* ----------------------------------------------------------- reference */

	showTools() {
		frappe.call({
			method: 'isoft_business_ai.api.list_tools',
			callback: r => {
				const esc = isoft_business_ai.esc;
				const tools = r.message || [];
				const groups = {};
				tools.forEach(t => { (groups[t.group] = groups[t.group] || []).push(t); });
				const html = Object.keys(groups).sort().map(g =>
					'<h5 style="text-transform:capitalize">' + esc(g) + '</h5><ul>' +
					groups[g].map(t =>
						'<li><code>' + esc(t.name) + '</code> — ' + esc(t.description) + '</li>'
					).join('') + '</ul>').join('');
				new frappe.ui.Dialog({
					title: __('What the assistant can look up'),
					size: 'large',
					fields: [{ fieldtype: 'HTML',
						options: '<div class="ibai-tools-dlg">' + html + '</div>' }],
				}).show();
			},
		});
	}
}
