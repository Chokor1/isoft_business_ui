// Quick assistant — a right-side panel for asking questions while working on
// an ERP document. The full workspace (/app/business-assistant) handles longer
// conversations, auditing and wide reports.
//
// Deliberately absent: a stop button, token streaming and attachments. The
// backend answers in one blocking call and reports its tools only once done,
// so any of those controls would be decoration.

frappe.provide('isoft_business_ai');

isoft_business_ai.Widget = class Widget {
	constructor() {
		this.conversation = null;
		this.busy = false;
		this.open = false;
		this.composing = false;      // IME composition in progress
		this.lastQuestion = '';
		// Documents already named in this conversation; re-offering one is noise.
		this.mentioned = new Set();
		this.context = null;         // the document attached to this conversation

		this.build();
		this.bind();
		this.restore();
	}

	/* ------------------------------------------------------------- markup */

	build() {
		const ico = isoft_business_ai.icon;

		// Hidden while the panel is open: the header owns the close button, and
		// this would land on top of the composer's send button.
		this.$launcher = $(
			'<button class="ibai-launcher" aria-expanded="false" aria-label="' +
			__('Business Assistant') + '">' +
			isoft_business_ai.galaxy(34) +
			'</button>'
		).appendTo(document.body);

		this.$panel = $(
			'<aside class="ibai-panel" role="complementary" aria-label="' + __('Business Assistant') + '">' +
				'<button class="ibai-grip" aria-label="' + __('Resize panel') + '" tabindex="-1"></button>' +

				'<header class="ibai-head">' +
					'<span class="ibai-head-mark">' + isoft_business_ai.galaxy(20) + '</span>' +
					'<div class="ibai-head-name">' + __('Business Assistant') + '</div>' +
					'<nav class="ibai-head-actions">' +
						'<button class="ibai-ico ibai-act-new" aria-label="' + __('New chat') + '" title="' + __('New chat') + '">' + ico('<path d="M12 5v14M5 12h14"/>') + '</button>' +
						'<button class="ibai-ico ibai-act-history" aria-label="' + __('History') + '" title="' + __('History') + '">' + ico('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>') + '</button>' +
						'<button class="ibai-ico ibai-act-expand" aria-label="' + __('Open full workspace') + '" title="' + __('Open full workspace') + '">' + ico('<path d="M15 3h6v6M14 10l7-7M9 21H3v-6M10 14l-7 7"/>') + '</button>' +
						'<button class="ibai-ico ibai-act-close" aria-label="' + __('Close') + '" title="' + __('Close') + '">' + ico('<path d="M18 6 6 18M6 6l12 12"/>') + '</button>' +
					'</nav>' +
				'</header>' +

				'<div class="ibai-context" hidden></div>' +

				'<div class="ibai-body">' +
					'<div class="ibai-drawer" hidden>' +
						'<div class="ibai-drawer-top">' +
							'<span class="ibai-drawer-title">' + __('History') + '</span>' +
							'<button class="ibai-ico ibai-drawer-close" aria-label="' + __('Close history') + '">' + ico('<path d="M18 6 6 18M6 6l12 12"/>') + '</button>' +
						'</div>' +
						'<div class="ibai-search"><input type="search" autocomplete="off" placeholder="' + __('Search conversations') + '"></div>' +
						'<div class="ibai-hlist"></div>' +
					'</div>' +
					'<div class="ibai-stream" tabindex="0"></div>' +
					'<button class="ibai-jump" hidden>' + ico('<path d="M12 5v14M19 12l-7 7-7-7"/>', 12) + '<span>' + __('Jump to latest') + '</span></button>' +
				'</div>' +

				'<div class="ibai-composer">' +
					'<div class="ibai-field">' +
						'<textarea class="ibai-input" rows="1" aria-label="' + __('Message') + '" ' +
							'placeholder="' + __('Ask about your ERP data…') + '"></textarea>' +
						'<button class="ibai-send" aria-label="' + __('Send') + '" disabled>' +
							ico('<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/>', 16) + '</button>' +
					'</div>' +
					'<div class="ibai-foot">' +
						'<span class="ibai-hint">' + __('Review important results before taking action.') + '</span>' +
						'<button class="ibai-mute" aria-label="' + __('Sound') + '"></button>' +
					'</div>' +
				'</div>' +
			'</aside>'
		).appendTo(document.body);

		this.$stream = this.$panel.find('.ibai-stream');
		this.$input = this.$panel.find('.ibai-input');
		this.$send = this.$panel.find('.ibai-send');
		this.$drawer = this.$panel.find('.ibai-drawer');
		this.$hlist = this.$panel.find('.ibai-hlist');
		this.$search = this.$panel.find('.ibai-search input');
		this.$contextBar = this.$panel.find('.ibai-context');
		this.$mute = this.$panel.find('.ibai-mute');
		this.$jump = this.$panel.find('.ibai-jump');

		this.scroll = isoft_business_ai.scroller(this.$stream, this.$jump);
		this.drawMute();
		this.welcome();
	}

	/* ------------------------------------------------------------- events */

	bind() {
		const $composer = this.$panel.find('.ibai-composer');
		isoft_business_ai.attachMentions(this.$input, $composer);
		// After attachMentions, so the @ menu gets first refusal on a keystroke.
		isoft_business_ai.typeahead(this.$input, $composer, text => {
			this.$input.val(text);
			this.sizeInput();
			this.send();
		});
		isoft_business_ai.fitPlaceholder(this.$input,
			__('Ask about your ERP data…'), __('Ask a question…'));

		this.$launcher.on('click', () => this.toggle());
		this.$panel.find('.ibai-act-close').on('click', () => this.toggle(false));
		this.$panel.find('.ibai-act-new').on('click', () => this.newChat());
		this.$panel.find('.ibai-act-history').on('click', () => this.drawer());
		this.$panel.find('.ibai-drawer-close').on('click', () => this.drawer(false));
		// A new tab, like the other ISOFT apps: the workspace is a place you
		// keep open beside the ERP, not a route you navigate away to. Opened
		// with window.open rather than a target=_blank link because the v13
		// router hijacks clicks on /app links into the current tab.
		this.$panel.find('.ibai-act-expand').on('click', () => {
			this.toggle(false);
			window.open('/app/business-assistant', '_blank', 'noopener');
		});
		this.$send.on('click', () => this.send());
		this.$mute.on('click', () => {
			const on = !isoft_business_ai.sound.enabled();
			isoft_business_ai.sound.setEnabled(on);
			this.drawMute();
			if (on) isoft_business_ai.sound.received();
		});

		// Enter sends, Shift+Enter breaks. Never while an IME is composing.
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

		// Clicking away closes it, like every other overlay in the desk.
		//
		// mousedown, not click: a click that began inside the panel and ended
		// outside it - dragging to select an answer - must not count as away.
		// The launcher is excluded because its own handler already toggles,
		// and a Frappe dialog opened from the panel counts as inside.
		//
		// Capture phase, which is why this is addEventListener and not jQuery.
		// The menus inside the composer act on mousedown and empty themselves,
		// so by the time a bubbling handler runs, the row that was clicked is
		// already detached - and closest() on a detached node finds nothing,
		// which read as a click outside and closed the panel every time a
		// mention was picked.
		document.addEventListener('mousedown', e => {
			if (!this.open) return;
			const el = e.target;
			if (el && el.closest && el.closest(
				'.ibai-panel, .ibai-launcher, .modal, .modal-backdrop, .ibai-menu')) {
				return;
			}
			this.toggle(false);
		}, true);

		// Escape dismisses one layer at a time: an open row menu, then the
		// history drawer, then the panel itself.
		$(document).on('keydown.ibai', e => {
			if (e.key !== 'Escape' || !this.open) return;
			if ($('.ibai-menu').length) return;
			if (!this.$drawer.prop('hidden')) { this.drawer(false); return; }
			this.toggle(false);
		});

		// The desk is a single page app: the route changes underneath us.
		$(document).on('page-change.ibai', () => {
			this.onRoute();
			if (this.open) this.refreshContext();
		});
		this.onRoute();

		this.bindResize();
	}

	/** The full workspace already is the assistant; a second one floating over
	 *  it is noise, so the launcher and any open panel stand down there. */
	onRoute() {
		const here = (frappe.get_route() || [])[0] === 'business-assistant';
		this.$launcher.toggleClass('ibai-hidden', here);
		if (here && this.open) this.toggle(false);
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

	/* -------------------------------------------------------- open / resize */

	restore() {
		try {
			const w = parseInt(localStorage.getItem('ibai_panel_w'), 10);
			if (w) this.setWidth(w);
			if (localStorage.getItem('ibai_widget_open') === '1' &&
				!this.$launcher.hasClass('ibai-hidden')) this.toggle(true);
		} catch (e) {
			// Private mode or blocked storage: start closed at the default width.
		}
	}

	setWidth(px) {
		const max = Math.min(640, Math.max(380, window.innerWidth - 120));
		const w = Math.max(380, Math.min(px, max));
		this.$panel.css('width', w + 'px');
		try { localStorage.setItem('ibai_panel_w', String(w)); } catch (e) { /* ignore */ }
	}

	bindResize() {
		const $grip = this.$panel.find('.ibai-grip');
		let dragging = false;

		const move = e => {
			if (!dragging) return;
			this.setWidth(window.innerWidth - e.clientX);
		};
		const stop = () => {
			if (!dragging) return;
			dragging = false;
			$grip.removeClass('is-dragging');
			$(document.body).removeClass('ibai-resizing');
			$(document).off('mousemove.ibaigrip mouseup.ibaigrip');
		};

		$grip.on('mousedown', e => {
			e.preventDefault();
			dragging = true;
			$grip.addClass('is-dragging');
			$(document.body).addClass('ibai-resizing');
			$(document).on('mousemove.ibaigrip', move).on('mouseup.ibaigrip', stop);
		});
		// Keyboard-resizable too, since the grip is a real button.
		$grip.on('keydown', e => {
			const step = e.shiftKey ? 40 : 16;
			const current = this.$panel.outerWidth();
			if (e.key === 'ArrowLeft') { e.preventDefault(); this.setWidth(current + step); }
			if (e.key === 'ArrowRight') { e.preventDefault(); this.setWidth(current - step); }
		});
		$(window).on('resize.ibai', () => this.setWidth(this.$panel.outerWidth()));
	}

	toggle(force) {
		this.open = force === undefined ? !this.open : force;
		this.$panel.toggleClass('is-open', this.open);
		this.$launcher.toggleClass('is-open', this.open);
		this.$launcher.attr('aria-expanded', this.open ? 'true' : 'false');
		try {
			localStorage.setItem('ibai_widget_open', this.open ? '1' : '0');
		} catch (e) { /* ignore */ }

		if (!this.open) return;
		// Sit below the desk navbar so ERP navigation stays reachable.
		const nav = $('.navbar').first();
		this.$panel.css('top', (nav.length ? nav.outerHeight() : 0) + 'px');
		this.refreshContext();
		this.$panel.attr('tabindex', '-1').focus();
		setTimeout(() => this.$input.focus(), 160);
	}

	/* ------------------------------------------------------------- context */

	/** The document this conversation is about, shown in the header. */
	refreshContext() {
		const here = isoft_business_ai.currentDocument();
		this.renderContext();
		if (!here || this.context) return;
		if (this.mentioned.has(here.doctype + ':' + here.name)) return;

		frappe.call({
			method: 'isoft_business_ai.api.describe_document',
			args: { doctype: here.doctype, name: here.name },
			callback: r => {
				const d = r.message;
				if (!d || !d.ok || !this.open) return;
				this.offered = d;
				this.renderContext();
			},
		});
	}

	renderContext() {
		const $bar = this.$contextBar.empty();
		const show = this.context || this.offered;
		if (!show) { $bar.prop('hidden', true); return; }
		$bar.prop('hidden', false);

		if (this.context) {
			const $chip = $('<span class="ibai-context-chip"></span>');
			$('<span class="dt"></span>').text(this.context.doctype).appendTo($chip);
			$('<span class="nm"></span>').text(this.context.name).appendTo($chip);
			$('<button class="ibai-context-x" aria-label="' + __('Remove context') + '"></button>')
				.html(isoft_business_ai.icon('<path d="M18 6 6 18M6 6l12 12"/>', 11))
				.on('click', () => { this.context = null; this.renderContext(); })
				.appendTo($chip);
			$('<span></span>').text(__('In context') + ':').appendTo($bar);
			$bar.append($chip);
			return;
		}

		const d = this.offered;
		const label = d.title ? d.doctype + ' · ' + d.title : d.doctype;
		$('<button class="ibai-context-add"></button>')
			.text('@ ' + label + '  ' + d.name)
			.attr('title', __('Add this document to the conversation'))
			.on('click', () => {
				this.context = { doctype: d.doctype, name: d.name };
				this.offered = null;
				this.renderContext();
				this.$input.focus();
			})
			.appendTo($bar);
	}

	/* ------------------------------------------------------------- history */

	drawer(force) {
		const show = force === undefined ? this.$drawer.prop('hidden') : force;
		this.$drawer.prop('hidden', !show);
		this.$panel.find('.ibai-act-history').attr('aria-expanded', show ? 'true' : 'false');
		if (!show) { this.$input.focus(); return; }
		this.loadHistory();
		setTimeout(() => this.$search.focus(), 60);
	}

	loadHistory() {
		const term = (this.$search.val() || '').trim();
		this.$hlist.html('<div class="ibai-empty">' + __('Loading…') + '</div>');
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

		const open = () => this.openConversation(c.name);
		$main.on('click', open);
		$row.on('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });

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
					callback: () => this.loadHistory(),
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
					if (this.conversation === c.name) this.newChat();
					this.loadHistory();
				},
			}),
			__('Delete'),
			true
		);
	}

	openConversation(name) {
		frappe.call({
			method: 'isoft_business_ai.api.get_conversation',
			args: { name },
			callback: r => {
				if (!r.message) return;
				this.conversation = name;
				this.mentioned.clear();
				this.context = null;
				this.$stream.empty();
				(r.message.messages || []).forEach(m => {
					if (m.role === 'user') {
						isoft_business_ai.extractMentions(m.content).forEach(k => this.mentioned.add(k));
						this.addUser(m.content, m.creation);
					} else {
						this.addAnswer({ answer: m.content, results: m.results || [],
							message: m.name }, m.creation);
					}
				});
				this.drawer(false);
				this.scroll.toBottom(true);
			},
		});
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

				if (d.company) $w.find('.ibai-welcome-sub').text(d.company);

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

	newChat() {
		this.conversation = null;
		this.mentioned.clear();
		this.context = null;
		this.offered = null;
		this.drawer(false);
		this.welcome();
		this.$input.val('');
		this.sizeInput();
		this.refreshContext();
		this.$input.focus();
	}

	/* ---------------------------------------------------------------- send */

	send(retryText) {
		if (this.busy) return;
		let question = retryText !== undefined ? retryText : (this.$input.val() || '').trim();
		if (!question) return;

		// A header context chip is a mention the user does not have to type.
		if (this.context) {
			const token = isoft_business_ai.mentionToken(this.context.doctype, this.context.name);
			if (question.indexOf(token) === -1) question = token + ' ' + question;
		}

		isoft_business_ai.extractMentions(question).forEach(k => this.mentioned.add(k));
		this.lastQuestion = question;

		if (retryText === undefined) { this.$input.val(''); this.sizeInput(); }
		this.$panel.find('.ibai-fail').remove();
		this.$stream.find('.ibai-welcome').remove();
		this.drawer(false);

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
				this.addAnswer(r.message);
				isoft_business_ai.sound.received();
			},
			error: () => {
				$working.remove();
				this.busy = false;
				this.addFailure();
				isoft_business_ai.sound.error();
			},
			// v13 can call neither callback on some failures; always() settles it.
			always: () => {
				if (!this.busy) return;
				$working.remove();
				this.busy = false;
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

	addAnswer(payload, when) {
		const $turn = $('<div class="ibai-turn ibai-turn-bot"></div>');

		if ((payload.results || []).length) {
			$turn.append(isoft_business_ai.render_steps(payload.results));
		}
		const $answer = $('<div class="ibai-answer"></div>')
			.html(isoft_business_ai.format_text(payload.answer));
		$turn.append($answer);

		(payload.results || []).forEach((res, i) => {
			$turn.append(isoft_business_ai.render_result(res, {
				message_name: payload.message, index: i,
			}));
		});

		const $tools = $('<div class="ibai-turn-tools"></div>');
		const $copy = $('<button class="ibai-tool"></button>')
			.html(isoft_business_ai.icon('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', 12) +
				'<span>' + __('Copy') + '</span>')
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

		if (when) {
			$('<div class="ibai-when"></div>')
				.text(isoft_business_ai.when(when)).appendTo($turn);
		}
		$turn.appendTo(this.$stream);
		this.scroll.follow();
	}
};

$(document).on('app_ready', function () {
	// A disabled assistant must not advertise itself: no launcher at all,
	// rather than a button that greets the user with an error.
	if (!frappe.boot || !isoft_business_ai.can_use()) return;
	if (!isoft_business_ai.is_enabled()) return;
	// Enabled with no key is a misconfiguration, not a feature. Managers see it
	// so they can diagnose; nobody else gets a broken button.
	if (!isoft_business_ai.is_configured() && !isoft_business_ai.flags().is_manager) return;
	if (isoft_business_ai._widget) return;
	isoft_business_ai._widget = new isoft_business_ai.Widget();
});
