// Shared rendering for the assistant's two surfaces — the quick panel and the
// full workspace. Loaded via app_include_js so both have it before any page
// script runs, and so a table, a figure or a document link looks identical
// wherever it appears.

frappe.provide('isoft_business_ai');

const IBAI = isoft_business_ai;

/* ------------------------------------------------------------------ basics */

IBAI.esc = function (value) {
	return frappe.utils.escape_html(String(value == null ? '' : value));
};

IBAI.icon = function (path, size) {
	return '<svg viewBox="0 0 24 24" width="' + (size || 14) + '" height="' + (size || 14) +
		'" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
		'stroke-linejoin="round">' + path + '</svg>';
};

/* ------------------------------------------------------------- capabilities */

/**
 * The product mark: a barred spiral seen edge-on-ish. Drawn rather than shipped
 * as an asset so it inherits the theme tokens, and every instance gets its own
 * gradient ids because SVG gradient ids are document-global.
 */
IBAI._gid = 0;
IBAI.galaxy = function (size) {
	const id = 'ibg' + (++IBAI._gid);
	// The arms start at the core's edge, not beyond it: start them any further
	// out and at launcher size (52px) they read as two detached commas.
	return '' +
		'<svg class="ibai-galaxy" viewBox="0 0 48 48" width="' + size + '" height="' + size + '" ' +
			'fill="none" aria-hidden="true" focusable="false">' +
		'<defs>' +
			'<radialGradient id="' + id + 'c" cx="50%" cy="50%" r="50%">' +
				'<stop class="g0" offset="0%"/>' +
				'<stop class="g1" offset="38%"/>' +
				'<stop class="g2" offset="100%"/>' +
			'</radialGradient>' +
			'<linearGradient id="' + id + 'a" x1="0%" y1="0%" x2="100%" y2="100%">' +
				'<stop class="a0" offset="0%"/><stop class="a1" offset="100%"/>' +
			'</linearGradient>' +
		'</defs>' +
		'<g class="ibai-galaxy-disc">' +
			'<ellipse cx="24" cy="24" rx="20" ry="7.4" stroke="url(#' + id + 'a)" ' +
				'stroke-width="1" opacity=".22"/>' +
			'<path d="M24.8 20.6c6.2-2.1 13.8.8 14.6 5.8.8 5.2-5.4 9.8-12 8.8" ' +
				'stroke="url(#' + id + 'a)" stroke-width="2.6" stroke-linecap="round"/>' +
			'<path d="M23.2 27.4c-6.2 2.1-13.8-.8-14.6-5.8-.8-5.2 5.4-9.8 12-8.8" ' +
				'stroke="url(#' + id + 'a)" stroke-width="2.6" stroke-linecap="round"/>' +
		'</g>' +
		'<circle cx="24" cy="24" r="6.4" fill="url(#' + id + 'c)"/>' +
		'<circle class="ibai-galaxy-star" cx="40" cy="10" r="1.1"/>' +
		'<circle class="ibai-galaxy-star" cx="8" cy="38" r=".9"/>' +
		'<circle class="ibai-galaxy-star" cx="42" cy="39" r=".7"/>' +
		'<circle class="ibai-galaxy-star" cx="6.5" cy="10.5" r=".7"/>' +
		'</svg>';
};

IBAI.flags = function () {
	return (frappe.boot && frappe.boot.isoft_business_ai) || {};
};
// The server's rule, not a second guess at it: boot.py already decided, and
// reading roles here let a System Manager without the role mount the launcher
// and meet the "you need the role" error on their first click.
IBAI.can_use = function () { return !!IBAI.flags().can_use; };
IBAI.is_enabled = function () { return !!IBAI.flags().enabled; };
IBAI.is_configured = function () { return !!IBAI.flags().configured; };

/* ----------------------------------------------------------------- copying */

/**
 * Copy on a deliberate click. The clipboard API is refused in some app views,
 * so a rejection falls back to selecting the text for the viewer to copy.
 */
IBAI.copy = function (text, $button, $fallbackSource) {
	const done = () => {
		if (!$button) return;
		const was = $button.html();
		$button.html(IBAI.icon('<path d="M20 6 9 17l-5-5"/>', 12) + '<span>' + __('Copied') + '</span>');
		setTimeout(() => $button.html(was), 1400);
	};
	try {
		navigator.clipboard.writeText(text).then(done, () => IBAI._select($fallbackSource));
	} catch (e) {
		IBAI._select($fallbackSource);
	}
};

IBAI._select = function ($source) {
	if (!$source || !$source.length) return;
	try {
		const range = document.createRange();
		range.selectNodeContents($source[0]);
		const sel = window.getSelection();
		sel.removeAllRanges();
		sel.addRange(range);
		frappe.show_alert({ message: __('Press Ctrl+C to copy'), indicator: 'blue' });
	} catch (e) {
		/* nothing more we can offer */
	}
};

/** A result table as tab-separated text, for pasting into a spreadsheet. */
IBAI.resultToText = function (res) {
	const cols = res.columns || [];
	const lines = [cols.map(c => c.label).join('\t')];
	(res.rows || []).forEach(row => {
		lines.push(cols.map(c => {
			const v = row[c.key];
			return v == null ? '' : String(v);
		}).join('\t'));
	});
	if (res.source) lines.push('', res.source);
	return lines.join('\n');
};

/* -------------------------------------------------------------- formatting */

IBAI.format_cell = function (value, col) {
	if (value === null || value === undefined || value === '') return '';
	if (col.type === 'currency') return format_currency(value);
	if (col.type === 'float') return format_number(value, null, 2);
	if (col.type === 'int') return format_number(value, null, 0);
	if (col.type === 'percent') return format_number(value, null, 1) + '%';
	return IBAI.esc(value);
};

IBAI.is_numeric = function (col) {
	return ['currency', 'float', 'int', 'percent'].indexOf(col.type) !== -1;
};

/* ------------------------------------------------------------------ mentions */
// A document is referenced as @[DocType:Name]. The brackets matter: an ERPNext
// name can hold both spaces and slashes ("FT FT3726S2554N/999"), so a looser
// form could not be parsed back.

IBAI.MENTION = /@\[([^:\]]{1,140}):([^\]]{1,200})\]/g;

IBAI.mentionToken = function (doctype, name) {
	return '@[' + doctype + ':' + name + ']';
};

IBAI.extractMentions = function (text) {
	const re = new RegExp(IBAI.MENTION.source, 'g');
	const out = [];
	let m;
	while ((m = re.exec(text || ''))) out.push(m[1] + ':' + m[2]);
	return out;
};

/** Mention markup as plain words — titles are rendered as text. */
IBAI.stripMentions = function (text) {
	return (text || '').replace(new RegExp(IBAI.MENTION.source, 'g'), '$1 $2').trim();
};

/** The document the user is looking at right now, from the desk route. */
IBAI.currentDocument = function () {
	try {
		const route = frappe.get_route() || [];
		if (route[0] !== 'Form' || !route[1] || !route[2]) return null;
		const doctype = route[1];
		// Not every form holds a business record. Sitting on a settings page
		// used to offer that settings page as a mention - first in the list
		// and pre-selected, so one Tab wrote "@[Isoft Business AI Settings:
		// Isoft Business AI Settings]" into the question.
		const known = IBAI.knownDoctype(doctype);
		if (known === false) return null;
		if (known === null) {
			const meta = frappe.get_meta ? frappe.get_meta(doctype) : null;
			if (meta && (meta.issingle || meta.istable)) return null;
		}
		return { doctype: doctype, name: decodeURIComponent(route[2]) };
	} catch (e) {
		/* not on a form */
	}
	return null;
};

/* ------------------------------------------------------------ answer markup */

/**
 * A deliberately small markdown subset: headings, bullets, numbered lists,
 * inline code, bold, links and mention chips. Everything is escaped first, so
 * the model cannot inject markup — it can only ask for these shapes.
 */
IBAI.format_text = function (text) {
	const esc = IBAI.esc;
	const inline = s => esc(s)
		.replace(/`([^`]+)`/g, (m, c) => '<code>' + c + '</code>')
		.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
		.replace(new RegExp(IBAI.MENTION.source, 'g'),
			(m, dt, nm) => '<span class="ibai-mention">' + esc(dt) + ' ' + esc(nm) + '</span>')
		.replace(/(https?:\/\/[^\s<]+)/g,
			'<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

	const out = [];
	let list = null;            // 'ul' | 'ol' | null
	const closeList = () => { if (list) { out.push('</' + list + '>'); list = null; } };

	(text || '').split('\n').forEach(raw => {
		const line = raw.replace(/\s+$/, '');
		if (!line.trim()) { closeList(); return; }

		const heading = line.match(/^#{1,4}\s+(.*)$/);
		if (heading) { closeList(); out.push('<h4>' + inline(heading[1]) + '</h4>'); return; }

		const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
		if (bullet) {
			if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; }
			out.push('<li>' + inline(bullet[1]) + '</li>');
			return;
		}
		const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
		if (numbered) {
			if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; }
			out.push('<li>' + inline(numbered[1]) + '</li>');
			return;
		}
		closeList();
		out.push('<p>' + inline(line) + '</p>');
	});
	closeList();
	return out.join('');
};

/* -------------------------------------------------------------------- steps */

/**
 * What the assistant actually did, reported after the answer arrives. The
 * backend returns the tools only once the turn is complete, so there is no
 * honest way to show this while it runs — and inventing it would be worse
 * than showing nothing.
 */
IBAI.render_steps = function (results) {
	const $wrap = $('<div class="ibai-steps"></div>');
	(results || []).forEach(r => {
		const $s = $('<span class="ibai-step"></span>');
		$(IBAI.icon('<path d="M20 6 9 17l-5-5"/>', 11)).appendTo($s);
		$('<b></b>').text(r.tool).appendTo($s);
		const bits = [];
		if (typeof r.row_count === 'number') {
			bits.push(r.row_count + ' ' + (r.row_count === 1 ? __('row') : __('rows')));
		}
		if (r.elapsed_ms) bits.push(r.elapsed_ms + ' ms');
		if (bits.length) $('<i></i>').text(bits.join(' · ')).appendTo($s);
		if (r.source) $s.attr('title', r.source);
		$wrap.append($s);
	});
	return $wrap;
};

/* -------------------------------------------------------------- composer */

/**
 * A placeholder that describes the scope reads well on a desktop and gets cut
 * in half on a phone, so the narrow screen gets a short one instead.
 */
/**
 * The invitation in the empty box, which is the only instruction most people
 * will read. Naming the things it can be asked about beats "ask a question",
 * and a part number nobody recognises is the one that sends it looking outside
 * the ERP, so it earns its place in the list.
 *
 * The wording lives here, not at the two call sites, because one of them is a
 * desk Page script that browsers cache with no version check - a change there
 * can sit unshipped for weeks. The arguments are accepted and ignored.
 */
IBAI.PLACEHOLDER = {
	long: 'Ask about sales, stock, money, a document, or an item you don\u2019t recognise\u2026',
	short: 'Ask about your business\u2026',
};
IBAI.fitPlaceholder = function ($input) {
	// Measured against the box it has to fit, not the window: the quick panel
	// is narrow on the widest screen, and the long version wrapped onto a
	// second line there and was clipped by the composer's height.
	const apply = () => {
		const room = $input.outerWidth() || window.innerWidth;
		$input.attr('placeholder', room < 420
			? __(IBAI.PLACEHOLDER.short) : __(IBAI.PLACEHOLDER.long));
	};
	apply();
	$(window).on('resize.ibaiph', apply);
	try {
		// The panel can be dragged wider, which no window event reports.
		new ResizeObserver(apply).observe($input[0]);
	} catch (e) { /* the window handler still covers the common case */ }
};

/* ------------------------------------------------------------------ results */

/**
 * One tool result: the document header where there is one, the table, its
 * provenance line, and links to anything worth opening.
 * opts: { message_name, index, wide }
 */
IBAI.render_result = function (res, opts) {
	opts = opts || {};
	// A lookup the model needed on the way to the answer is not an answer. It
	// still shows in the step strip above, so the provenance is intact; printing
	// its table under the answer made "here is the customer you named" look like
	// the result of the question.
	if (res.aux) return $();
	const esc = IBAI.esc;
	const columns = res.columns || [];
	const rows = res.rows || [];
	const $wrap = $('<div class="ibai-result"></div>');
	if (opts.wide && columns.length > 5) $wrap.addClass('is-wide');
	// Enough columns to read as a sheet rather than a list: pin the labels so
	// the figures scroll under them. The labels are the leading run of
	// non-numeric columns, capped at two - a balancete leads with a code AND a
	// description, and pinning only the code leaves the name scrolling away in
	// clipped fragments, which reads as corruption rather than as scrolling.
	let pinned = 0;
	if (columns.length >= 5) {
		$wrap.addClass('is-sheet');
		while (pinned < columns.length && pinned < 2 && !IBAI.is_numeric(columns[pinned])) {
			pinned++;
		}
		if (pinned) $wrap.addClass('pin-' + pinned);
	}

	if (res.header && Object.keys(res.header).length) {
		const $dl = $('<dl class="ibai-doc-header"></dl>');
		Object.keys(res.header).forEach(k => {
			$('<dt></dt>').text(__(k)).appendTo($dl);
			$('<dd></dd>').text(String(res.header[k])).appendTo($dl);
		});
		$wrap.append($dl);
	}

	// Pictures and files that belong to the document. The model never gets
	// these URLs; it is only told the files exist, so it describes them while
	// the browser is what actually shows them.
	if ((res.media || []).length) {
		const $media = $('<div class="ibai-media"></div>');
		res.media.forEach(m => {
			// Only site-relative or http(s) URLs are ever followed: these
			// strings come out of the database, and a stored "javascript:..."
			// must not become a live link.
			const url = String(m.url || '');
			if (!/^(https?:\/\/|\/)/.test(url)) return;
			const name = m.name || url.split('/').pop();
			if (m.kind === 'image') {
				// The picture is the answer, so it is shown at a size worth
				// looking at, with the place it came from as a caption under
				// it rather than a link standing in for it.
				const $fig = $('<figure class="ibai-media-fig"></figure>');
				const $a = $('<a class="ibai-media-img" target="_blank" rel="noopener"></a>')
					.attr('href', m.source || url).attr('title', name);
				$('<img>').attr('src', url).attr('alt', name)
					.attr('loading', 'lazy')
					// No referrer: some sites refuse to serve a picture to
					// another origin, and the ERP's address is not theirs to
					// collect either.
					.attr('referrerpolicy', 'no-referrer')
					// A picture that will not load leaves a link to where it
					// lives, rather than a broken icon or a silent gap.
					.on('error', function () {
						const $f = $(this).closest('.ibai-media-fig');
						$f.addClass('is-missing');
						$f.find('.ibai-media-img').remove();
						$('<a class="ibai-media-file" target="_blank" rel="noopener"></a>')
							.attr('href', m.source || url)
							.text(__('Picture at {0}', [name]))
							.prependTo($f);
					})
					.appendTo($a);
				$fig.append($a);
				if (m.source) {
					const $cap = $('<figcaption></figcaption>');
					$('<a target="_blank" rel="noopener"></a>')
						.attr('href', m.source).text(name).appendTo($cap);
					$cap.appendTo($fig);
				} else if (name) {
					$('<figcaption></figcaption>').text(name).appendTo($fig);
				}
				$media.append($fig);
			} else {
				const $a = $('<a class="ibai-media-file" target="_blank" rel="noopener"></a>')
					.attr('href', url);
				$a.append(IBAI.icon('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
					'<path d="M14 2v6h6"/>', 13));
				$('<span></span>').text(name).appendTo($a);
				$media.append($a);
			}
		});
		if ($media.children().length) $wrap.append($media);
	}

	if (rows.length) {
		const head = columns.map((c, i) =>
			'<th class="' + (IBAI.is_numeric(c) ? 'ibai-num' : '') +
			(i < pinned ? ' ibai-pin ibai-pin-' + i : '') + '">' +
			esc(__(c.label)) + '</th>').join('');
		// Text cells carry their own value as a title: a wide table clips them
		// so the numeric columns stay on screen, and the full text has to stay
		// reachable without scrolling sideways.
		const body = rows.map(row => {
			// A tool may mark a row as a subtotal or a total; the marker is not
			// a column, so it never reaches format_cell.
			const mark = row._style === 'total' ? ' class="ibai-r-total"'
				: row._style === 'subtotal' ? ' class="ibai-r-subtotal"' : '';
			return '<tr' + mark + '>' + columns.map((c, i) => {
				const num = IBAI.is_numeric(c);
				const raw = row[c.key];
				const neg = num && typeof raw === 'number' && raw < 0;
				const title = (!num && raw != null && String(raw).trim())
					? ' title="' + esc(String(raw).trim()) + '"' : '';
				const cls = (num ? 'ibai-num' : '') + (neg ? ' ibai-neg' : '') +
					(i < pinned ? ' ibai-pin ibai-pin-' + i : '');
				return '<td class="' + cls + '"' + title + '>' +
					IBAI.format_cell(raw, c) + '</td>';
			}).join('') + '</tr>';
		}).join('');
		$wrap.append(
			'<div class="ibai-table-wrap"><table class="ibai-table">' +
			'<thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>'
		);
		// The second pinned column has to sit exactly at the first one's right
		// edge, which is only knowable once the browser has laid the table out.
		// The same measurement decides whether pinning is affordable at all:
		// a general ledger pins Date and Account, and Account alone came to
		// 402px, so in the quick panel the two frozen columns were wider than
		// the panel and left the other six nothing - the complaint was that
		// everything except the frozen pair was too narrow to read.
		if (pinned > 0) {
			const table = $wrap.find('.ibai-table')[0];
			const wrapEl = $wrap.find('.ibai-table-wrap')[0];
			const fit = () => {
				const first = table.querySelector('thead th.ibai-pin-0');
				if (!first || !first.offsetWidth) return;
				table.style.setProperty('--ibai-pin-1', first.offsetWidth + 'px');

				const visible = wrapEl.clientWidth;
				if (!visible) return;
				const widthOf = n => {
					const th = table.querySelector('thead th.ibai-pin-' + n);
					return th ? th.offsetWidth : 0;
				};
				// Over this much of the view and the frozen block stops being a
				// help: what scrolls under it has no room to show anything.
				const budget = visible * 0.55;
				let keep = pinned;
				while (keep > 0) {
					let used = 0;
					for (let n = 0; n < keep; n++) used += widthOf(n);
					if (used <= budget) break;
					keep--;
				}
				$wrap.toggleClass('unpin-1', pinned > 1 && keep < 2);
				$wrap.toggleClass('unpin-all', keep < 1);
			};
			fit();
			if (window.ResizeObserver) {
				const ro = new ResizeObserver(fit);
				ro.observe(table);
				if (wrapEl) ro.observe(wrapEl);
			} else {
				$(window).on('resize.ibaipin', fit);
			}
		}
	}

	const $foot = $('<div class="ibai-source"></div>');
	const bits = [];
	if (res.source) bits.push(__('Source') + ': ' + res.source);
	if (rows.length) bits.push(rows.length + ' ' + __('rows'));
	if (res.truncated) bits.push(__('result truncated'));
	$('<span></span>').text(bits.join(' · ')).appendTo($foot);

	if (rows.length) {
		$foot.append(' · ');
		const $copy = $('<a class="ibai-export" href="#"></a>').text(__('Copy table'))
			.on('click', e => {
				e.preventDefault();
				IBAI.copy(IBAI.resultToText(res), null, $wrap.find('.ibai-table'));
			});
		$foot.append($copy);
	}
	if (opts.message_name && rows.length) {
		$foot.append(' · ');
		$foot.append($('<a class="ibai-export" href="#"></a>').text(__('Export Excel'))
			.on('click', e => {
				e.preventDefault();
				window.open('/api/method/isoft_business_ai.api.export_result?message=' +
					encodeURIComponent(opts.message_name) + '&index=' + (opts.index || 0));
			}));
	}
	if (res.note) $('<div class="ibai-note"></div>').text(res.note).appendTo($foot);
	$wrap.append($foot);

	if ((res.links || []).length) {
		const $links = $('<div class="ibai-links"></div>');
		res.links.forEach(l => {
			if (!l || !l.doctype || !l.name) return;
			// Routed through the desk router: v13 hijacks /app link clicks
			// anyway, and set_route keeps the assistant open over the document.
			const href = '/app/' + frappe.router.slug(l.doctype) + '/' + encodeURIComponent(l.name);
			$('<a class="ibai-link"></a>')
				.attr('href', href)
				.text(l.label || (l.doctype + ' ' + l.name))
				.on('click', e => {
					e.preventDefault();
					frappe.set_route('Form', l.doctype, l.name);
				})
				.appendTo($links);
		});
		$wrap.append($links);
	}
	return $wrap;
};

/* ----------------------------------------------------------------- history */

/** Relative time as plain text. comment_when() returns a <span> wrapper, which
 *  is wrong everywhere we set text content. */
IBAI.when = function (stamp) {
	try {
		return frappe.datetime.prettyDate(stamp, true) || '';
	} catch (e) {
		return '';
	}
};

/** Which history bucket a timestamp belongs in. */
IBAI.dateGroup = function (stamp) {
	try {
		const d = frappe.datetime.str_to_obj(stamp);
		const a = new Date(d.getFullYear(), d.getMonth(), d.getDate());
		const n = new Date();
		const b = new Date(n.getFullYear(), n.getMonth(), n.getDate());
		const days = Math.round((b - a) / 86400000);
		if (days <= 0) return __('Today');
		if (days === 1) return __('Yesterday');
		if (days <= 7) return __('Previous 7 days');
		if (days <= 30) return __('Previous 30 days');
		return __('Older');
	} catch (e) {
		return __('Older');
	}
};

/* ---------------------------------------------------------------- scrolling */

/**
 * Keeps the conversation pinned to the bottom only while the reader is already
 * there, so reading an older answer is never interrupted, and offers a jump
 * button when they have scrolled away.
 */
IBAI.scroller = function ($stream, $jump) {
	const NEAR = 140;
	let near = true;

	const atBottom = () => {
		const el = $stream[0];
		if (!el) return true;
		return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR;
	};

	$stream.on('scroll', () => {
		near = atBottom();
		if ($jump) $jump.prop('hidden', near);
	});

	const api = {
		isNear: () => near,
		toBottom(instant) {
			const el = $stream[0];
			if (!el) return;
			near = true;
			if ($jump) $jump.prop('hidden', true);
			if (instant) { el.scrollTop = el.scrollHeight; return; }
			$stream.stop().animate({ scrollTop: el.scrollHeight }, 180);
		},
		follow(instant) { if (near) api.toBottom(instant); },
	};
	if ($jump) $jump.on('click', () => api.toBottom());
	return api;
};

/* -------------------------------------------------------------------- sound */
// Synthesised rather than loaded: no asset to ship and nothing for the desk
// bundler to miss. Browsers refuse audio before a gesture, and the first tone
// only ever follows a click.

IBAI.sound = {
	_ctx: null,
	enabled() {
		try { return localStorage.getItem('ibai_sound') !== 'off'; } catch (e) { return true; }
	},
	setEnabled(on) {
		try { localStorage.setItem('ibai_sound', on ? 'on' : 'off'); } catch (e) { /* ignore */ }
	},
	ctx() {
		if (!this._ctx) {
			const AC = window.AudioContext || window.webkitAudioContext;
			if (!AC) return null;
			this._ctx = new AC();
		}
		if (this._ctx.state === 'suspended') this._ctx.resume();
		return this._ctx;
	},
	_play(notes, peak) {
		if (!this.enabled()) return;
		let ctx;
		try { ctx = this.ctx(); } catch (e) { return; }
		if (!ctx) return;
		notes.forEach(n => {
			const osc = ctx.createOscillator();
			const gain = ctx.createGain();
			osc.type = 'sine';
			osc.frequency.value = n[0];
			const t = ctx.currentTime + n[1];
			gain.gain.setValueAtTime(0.0001, t);
			gain.gain.exponentialRampToValueAtTime(peak, t + 0.012);
			gain.gain.exponentialRampToValueAtTime(0.0001, t + n[2]);
			osc.connect(gain);
			gain.connect(ctx.destination);
			osc.start(t);
			osc.stop(t + n[2] + 0.02);
		});
	},
	sent() { this._play([[523.25, 0, 0.08]], 0.04); },
	received() { this._play([[659.25, 0, 0.1], [880.0, 0.08, 0.14]], 0.05); },
	error() { this._play([[311.13, 0, 0.13], [233.08, 0.11, 0.18]], 0.05); },
};

/* ------------------------------------------------------- mention autocomplete */

/**
 * Every document type that can be mentioned, fetched once per page.
 *
 * Matching runs in the browser so two letters can offer Supplier before the
 * word is finished. A round trip per keystroke was slower than typing, which
 * is why nobody ever found out what could be mentioned.
 */
IBAI._doctypes = null;
IBAI._doctypesWaiting = null;
IBAI.loadDoctypes = function (then) {
	if (IBAI._doctypes) { if (then) then(IBAI._doctypes); return; }
	if (IBAI._doctypesWaiting) { if (then) IBAI._doctypesWaiting.push(then); return; }
	IBAI._doctypesWaiting = then ? [then] : [];
	const done = list => {
		IBAI._doctypes = list || [];
		const waiting = IBAI._doctypesWaiting || [];
		IBAI._doctypesWaiting = null;
		waiting.forEach(fn => fn(IBAI._doctypes));
	};
	frappe.call({
		method: 'isoft_business_ai.api.mention_catalogue',
		callback: r => done(r.message || []),
		error: () => done([]),
	});
};

/** Whether this type is one the assistant can be asked about at all. */
IBAI.knownDoctype = function (doctype) {
	const all = IBAI._doctypes;
	if (!all) return null;          // not loaded yet - caller decides
	return all.some(d => d.doctype === doctype);
};

/**
 * Match tier of a list of spellings, or -1 for no match.
 *
 * Only prefixes count, of the whole name or of a word inside it. Matching a
 * needle found anywhere at all is what made these suggestions useless: "cu"
 * offered Loan Security Pledge. Mirrors _rank() in ai/documents.py.
 */
IBAI._rankTerms = function (terms, needle) {
	let best = -1;
	(terms || []).forEach(term => {
		let rank;
		if (term === needle) rank = 0;
		else if (term.indexOf(needle) === 0) rank = 1;
		else if (term.split(' ').some(w => w.indexOf(needle) === 0)) rank = 2;
		else return;
		if (best === -1 || rank < best) best = rank;
	});
	return best;
};

/**
 * Document types matching a part-written word, best first.
 *
 * Three orders of preference, mirroring _score() in ai/documents.py. Match
 * quality decides first, so an exact name is never beaten by a word found
 * inside a longer one. Then the types people actually mention, which is what
 * makes "cli" offer Customer rather than Clinical Procedure. Only then does
 * the language the match came from break the tie - a Portuguese spelling
 * finds the type inside an English desk just as well.
 */
IBAI.matchDoctypes = function (word, limit) {
	const needle = IBAI.normalise(word || '').trim();
	if (!needle) return [];
	const hits = [];
	(IBAI._doctypes || []).forEach(d => {
		let other = 0;
		let rank = IBAI._rankTerms(d.terms, needle);
		if (rank === -1) {
			rank = IBAI._rankTerms(d.alt, needle);
			if (rank === -1) return;
			other = 1;
		}
		hits.push({ doctype: d.doctype, label: d.label, rank: rank,
			common: d.common ? 0 : 1, other: other });
	});
	hits.sort((a, b) => a.rank - b.rank || a.common - b.common ||
		a.other - b.other || a.label.localeCompare(b.label));
	return hits.slice(0, limit || 5);
};

/** The word being typed just before the caret, if it could name a type. */
IBAI.wordAtCaret = function (value, caret) {
	const upto = (value || '').slice(0, caret);
	const m = /([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*)$/.exec(upto);
	if (!m) return null;
	return { text: m[1], start: caret - m[1].length, end: caret };
};

/**
 * The mention being typed at the caret, in any of the three shapes people use:
 *
 *   "@acme"            - search everything
 *   "Supplier@acme"    - the type written first, which is how people reach for
 *                        it out loud ("fornecedor@...")
 *   "@Supplier:acme"   - the original shape, still accepted
 *
 * `resolve` turns the word before the @ into a real doctype, or null. It is
 * passed in rather than looked up here so this stays a pure function: without
 * it, "ali@isoft.co.ao" would scope an email address to some unlucky doctype.
 */
IBAI.mentionTokenAt = function (value, caret, resolve) {
	value = value || '';
	const upto = value.slice(0, caret);
	const at = upto.lastIndexOf('@');
	if (at === -1) return null;
	const after = upto.slice(at + 1);
	if (/[\]\n]/.test(after) || after.length > 80) return null;

	const before = IBAI.wordAtCaret(value, at);
	const scope = before && resolve ? resolve(before.text) : null;
	const colon = after.indexOf(':');
	const written = colon === -1 ? null : after.slice(0, colon).trim();
	const doctype = scope || (written && resolve ? resolve(written) : null) || null;

	return {
		// What gets replaced when something is picked: the type the user wrote
		// goes too, or "Supplier@" would be left stranded before the chip.
		start: scope ? before.start : at,
		end: caret,
		doctype: doctype,
		// A type written before the @ cannot also be written after the colon.
		query: scope ? after : (colon === -1 ? after : after.slice(colon + 1)),
		scoped: !!doctype,
		// Identity of the attempt, for discarding a reply that arrived late.
		key: (scope ? before.text : '') + '@' + after,
	};
};

/**
 * Wire @ mentions onto a textarea: the open document first, then a search
 * across the business document types, in either language.
 */
IBAI.attachMentions = function ($input, $anchor) {
	const $menu = $('<div class="ibai-mentions" hidden></div>').appendTo($anchor);
	let items = [];
	let active = 0;
	let token = null;
	let timer = null;

	IBAI.loadDoctypes();

	function close() {
		$menu.prop('hidden', true).empty();
		items = [];
		token = null;
	}

	/** Replace the mention being typed, and say whether the menu stays up. */
	function write(text, keepOpen) {
		const value = $input.val() || '';
		const el = $input[0];
		const caret = token.start + text.length;
		$input.val(value.slice(0, token.start) + text +
			(keepOpen ? '' : ' ') + value.slice(token.end));
		if (!keepOpen) { close(); }
		$input.focus();
		try { el.setSelectionRange(caret, caret); } catch (e) { /* ignore */ }
		$input.trigger('input');
	}

	function pick(item) {
		if (!item || !token) return;
		if (item.kind === 'doctype') {
			// Stage one: they chose a type. Leave the menu open and start
			// searching inside it, which is the whole point of choosing one.
			write(item.doctype + '@', true);
			return;
		}
		if (item.kind === 'empty') return;
		write(IBAI.mentionToken(item.doctype, item.name), false);
	}

	function head(text) {
		$('<div class="ibai-mention-head"></div>').text(text).appendTo($menu);
	}

	function draw() {
		$menu.empty();
		if (!items.length) { $menu.prop('hidden', true); return; }
		let lastKind = null;
		items.forEach((it, i) => {
			const kind = it.kind === 'doctype' ? 'doctype' : 'doc';
			if (kind !== lastKind) {
				lastKind = kind;
				head(kind === 'doctype' ? __('Type of document')
					: (token && token.doctype ? token.doctype : __('Documents')));
			}
			const $row = $('<div class="ibai-mention-row"></div>')
				.toggleClass('active', i === active)
				.toggleClass('is-doctype', it.kind === 'doctype')
				.toggleClass('is-empty', it.kind === 'empty');
			if (it.kind === 'doctype') {
				// Shown as "Supplier@", because that is what picking it writes.
				$('<span class="ibai-mention-nm"></span>')
					.text(it.label + '@').appendTo($row);
				if (it.label !== it.doctype) {
					$('<span class="ibai-mention-lb"></span>').text(it.doctype).appendTo($row);
				}
				$('<span class="ibai-mention-go"></span>').text('→').appendTo($row);
			} else if (it.kind === 'empty') {
				$('<span class="ibai-mention-nm"></span>').text(it.text).appendTo($row);
			} else {
				$('<span class="ibai-mention-dt"></span>')
					.text(it.dtLabel || it.doctype).appendTo($row);
				$('<span class="ibai-mention-nm"></span>').text(it.name).appendTo($row);
				if (it.label) $('<span class="ibai-mention-lb"></span>').text(it.label).appendTo($row);
				if (it.here) {
					$('<span class="ibai-mention-here"></span>').text(__('open now')).appendTo($row);
				}
			}
			if (it.kind !== 'empty') {
				$row.on('mousedown', e => { e.preventDefault(); pick(it); });
			}
			$menu.append($row);
		});
		$menu.prop('hidden', false);
	}

	/** Strong enough to mean a type, rather than the left half of an email.
	 *
	 * A word found inside a longer name counts in the user's own language but
	 * not in the other one, which is what keeps "ali@isoft.co.ao" an address.
	 */
	function asDoctype(word) {
		const found = IBAI.matchDoctypes(word, 1);
		if (!found.length) return null;
		return found[0].rank + found[0].other <= 2 ? found[0].doctype : null;
	}

	function read() {
		const el = $input[0];
		return IBAI.mentionTokenAt(el.value, el.selectionStart, asDoctype);
	}

	$input.on('input click keyup', e => {
		if (['ArrowDown', 'ArrowUp', 'Enter', 'Escape', 'Tab'].indexOf(e.key) !== -1) return;
		token = read();
		if (!token) return close();

		const here = IBAI.currentDocument();
		const seed = [];
		if (!token.scoped && here && (!token.query ||
				here.name.toLowerCase().indexOf(token.query.toLowerCase()) !== -1)) {
			seed.push({ kind: 'doc', doctype: here.doctype, name: here.name,
				label: '', here: true });
		}
		items = seed.slice();
		active = 0;
		draw();

		clearTimeout(timer);
		const snapshot = token;
		timer = setTimeout(() => {
			if (!token || token.key !== snapshot.key) return;
			const calls = [$.Deferred(), $.Deferred()];

			// Types only matter while they have not committed to one.
			if (snapshot.scoped) {
				calls[0].resolve([]);
			} else {
				calls[0].resolve(IBAI.matchDoctypes(snapshot.query, 5));
			}
			frappe.call({
				method: 'isoft_business_ai.api.search_documents',
				args: { query: snapshot.query, doctype: snapshot.doctype || undefined,
					limit: snapshot.scoped ? 10 : 6 },
				callback: r => calls[1].resolve(r.message || []),
				error: () => calls[1].resolve([]),
			});

			$.when.apply($, calls).done((types, docs) => {
				if (!token || token.key !== snapshot.key) return;
				const typeRows = (types || []).map(t => ({
					kind: 'doctype', doctype: t.doctype, label: t.label }));
				const docRows = (docs || [])
					.filter(x => !seed.some(s => s.doctype === x.doctype && s.name === x.name))
					.map(x => Object.assign({ kind: 'doc' }, x));
				items = seed.concat(typeRows, docRows).slice(0, 12);
				// A scope that matches nothing has to say so: otherwise the
				// menu just vanishes and it looks like the @ stopped working.
				if (!items.length && snapshot.scoped) {
					items = [{ kind: 'empty', text: snapshot.query
						? __('No {0} matching "{1}"', [snapshot.doctype, snapshot.query])
						: __('No {0} you can see', [snapshot.doctype]) }];
				}
				active = items.length && items[0].kind === 'empty' ? -1 : 0;
				draw();
			});
		}, 180);
	});

	// stopImmediatePropagation, not stopPropagation: both surfaces bind their
	// own Enter-sends handler on this same textarea, and it is bound after this
	// one, so stopping the bubble is not enough - without this, choosing a
	// mention with Enter picked the record AND sent the half-written question.
	$input.on('keydown', e => {
		if ($menu.prop('hidden') || !items.length) return;
		const real = items.filter(it => it.kind !== 'empty');
		const stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
		if (!real.length) { if (e.key === 'Escape') { stop(); close(); } return; }
		if (e.key === 'ArrowDown') { stop(); active = (active + 1) % items.length; draw(); }
		else if (e.key === 'ArrowUp') { stop(); active = (active - 1 + items.length) % items.length; draw(); }
		else if (e.key === 'Enter' || e.key === 'Tab') { stop(); pick(items[active]); }
		else if (e.key === 'Escape') { stop(); close(); }
	});
	$input.on('blur', () => setTimeout(close, 160));
	return { close: close, isOpen: () => !$menu.prop('hidden') };
};

/* --------------------------------------------------------------- suggestions */

/**
 * The catalogue of questions the assistant can answer, fetched once per page.
 * Two dozen short strings, so matching happens in the browser rather than a
 * round trip per keystroke.
 */
IBAI._suggestions = null;
IBAI.setSuggestions = function (list) {
	if (list && list.length) IBAI._suggestions = list;
};
IBAI.loadSuggestions = function (then) {
	// Normally already filled by the briefing call the opening screen makes.
	if (IBAI._suggestions) { then(IBAI._suggestions); return; }
	frappe.call({
		method: 'isoft_business_ai.api.suggestions',
		callback: r => { IBAI._suggestions = r.message || []; then(IBAI._suggestions); },
		error: () => { IBAI._suggestions = []; then([]); },
	});
};

/**
 * No questions on the opening screen. It greets with the company and an empty
 * box, and the catalogue is still there the moment anyone starts typing.
 *
 * Kept as a function returning nothing rather than deleted: both surfaces call
 * it, and a desk Page script is cached in localStorage with no version check,
 * so a browser can still be running last week's copy of the caller.
 */
IBAI.openingSuggestions = function () {
	return [];
};

IBAI.normalise = function (text) {
	text = (text || '').toLowerCase();
	try {
		// Angolan users type with and without accents; both should match.
		return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
	} catch (e) {
		return text;
	}
};

/** Best matches for what has been typed so far, closest first. */
IBAI.matchSuggestions = function (query, limit) {
	const q = IBAI.normalise(query).trim();
	if (!q) return [];
	const scored = [];
	(IBAI._suggestions || []).forEach((s, i) => {
		const t = IBAI.normalise(s.text);
		let rank;
		if (t.indexOf(q) === 0) rank = 0;
		else if (t.indexOf(' ' + q) > -1) rank = 1;
		else if (t.indexOf(q) > -1) rank = 2;
		else return;
		scored.push({ s, rank, i });
	});
	scored.sort((a, b) => a.rank - b.rank || a.i - b.i);
	return scored.slice(0, limit || 5).map(x => x.s);
};

/**
 * Suggest questions as the user types. Deliberately quiet: nothing on an empty
 * composer (the opening screen already offers a few), nothing while the @
 * mention menu is up, and no pre-selected row — Enter still sends what you
 * typed until you arrow into the list.
 */
IBAI.typeahead = function ($input, $anchor, onPick) {
	const $menu = $('<div class="ibai-typeahead" hidden></div>').appendTo($anchor);
	let items = [];
	let active = -1;

	function close() { $menu.prop('hidden', true).empty(); items = []; active = -1; }

	function mentionsOpen() {
		const $m = $anchor.find('.ibai-mentions');
		return $m.length && !$m.prop('hidden');
	}

	let word = null;

	function draw() {
		$menu.empty();
		if (!items.length) { close(); return; }
		let lastKind = null;
		items.forEach((it, i) => {
			if (it.kind !== lastKind) {
				lastKind = it.kind;
				$('<div class="ibai-typeahead-head"></div>')
					.text(it.kind === 'doctype' ? __('Mention a document type')
						: __('Suggestions'))
					.appendTo($menu);
			}
			const $row = $('<button type="button" class="ibai-typeahead-row"></button>')
				.toggleClass('active', i === active)
				.toggleClass('is-doctype', it.kind === 'doctype')
				.on('mousedown', e => { e.preventDefault(); pick(it); })
				.appendTo($menu);
			if (it.kind === 'doctype') {
				$('<span class="ibai-typeahead-nm"></span>')
					.text(it.label + '@').appendTo($row);
				$('<span class="ibai-typeahead-hint"></span>')
					.text(__('then type a name')).appendTo($row);
			} else {
				$row.text(it.text);
			}
		});
		$menu.prop('hidden', false);
	}

	function pick(it) {
		if (it.kind === 'doctype') {
			if (!word) return;
			// Hand over to the @ menu: write "Supplier@" where the part-typed
			// word was, and let that search inside the type.
			const el = $input[0];
			const value = el.value || '';
			const written = it.doctype + '@';
			const caret = word.start + written.length;
			$input.val(value.slice(0, word.start) + written + value.slice(word.end));
			close();
			$input.focus();
			try { el.setSelectionRange(caret, caret); } catch (e) { /* ignore */ }
			$input.trigger('input');
			return;
		}
		close();
		onPick(it.text);
	}

	function refresh() {
		if (mentionsOpen()) { close(); return; }
		const value = ($input.val() || '').trim();
		// Once it is a sentence of their own, stop second-guessing them.
		if (!value || value.length > 48) { close(); return; }
		if (!IBAI._suggestions) { IBAI.loadSuggestions(refresh); return; }
		if (!IBAI._doctypes) { IBAI.loadDoctypes(refresh); }

		const el = $input[0];
		word = IBAI.wordAtCaret(el.value, el.selectionStart);
		// Two letters is the whole point: "su" should reach Supplier without
		// anyone having to know that @ is what starts a mention.
		const types = word && word.text.length >= 2
			? IBAI.matchDoctypes(word.text, 3) : [];
		items = IBAI.matchSuggestions(value, 5)
			.map(s => Object.assign({ kind: 'question' }, s))
			.concat(types.map(t => Object.assign({ kind: 'doctype' }, t)));
		active = -1;
		draw();
	}

	$input.on('input', refresh);
	$input.on('blur', () => setTimeout(close, 120));
	// stopImmediatePropagation, not stopPropagation: the surface binds its own
	// Enter-sends handler on this same textarea, and stopPropagation would not
	// stop a sibling handler on the same element.
	$input.on('keydown', e => {
		if ($menu.prop('hidden') || !items.length) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault(); e.stopImmediatePropagation();
			active = (active + 1) % items.length; draw();
		} else if (e.key === 'ArrowUp') {
			e.preventDefault(); e.stopImmediatePropagation();
			active = (active <= 0 ? items.length : active) - 1; draw();
		} else if (e.key === 'Enter' && active > -1) {
			e.preventDefault(); e.stopImmediatePropagation();
			pick(items[active]);
		} else if (e.key === 'Escape') {
			e.preventDefault(); e.stopImmediatePropagation();
			close();
		}
	});

	// Submitting takes the question away, so the suggestions for it go too.
	// Bound after the handler above, so when that one picks a suggestion it
	// stops the event and this never runs; when nothing is selected it falls
	// through to the surface's own send, and the menu closes with it.
	//
	// Done here rather than in each surface's send(): one of them ships in a
	// desk Page script that browsers cache with no version check.
	$input.on('keydown', e => {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
			close();
		}
	});
	$anchor.on('mousedown', '.ibai-send', close);

	// No eager fetch: the briefing has almost certainly filled the cache by the
	// time anyone types, and a miss costs one call on the first keystroke.
	return { close, refresh };
};

/* ---------------------------------------------------------------- feedback */

/**
 * Report an answer as wrong. Recorded against the message with the tools that
 * ran; it changes nothing on its own, and the dialog says so, because a control
 * that implies it will retrain something would be a lie.
 */
IBAI.reportAnswer = function (messageName, $button) {
	if (!messageName) return;
	const d = new frappe.ui.Dialog({
		title: __('Report this answer'),
		fields: [
			{
				fieldname: 'verdict', fieldtype: 'Select', label: __('What is wrong with it?'),
				reqd: 1,
				options: [__('Wrong number'), __('Wrong interpretation'), __('Incomplete'),
					__('Should not have answered'), __('Unclear'), __('Other')].join('\n'),
			},
			{
				fieldname: 'comment', fieldtype: 'Small Text',
				label: __('What should it have said?'),
				description: __('The question, the answer and the queries that ran are saved automatically.'),
			},
			{
				fieldtype: 'HTML',
				options: '<p style="font-size:12px;color:var(--text-muted,#6b7a8c);margin:0">' +
					__('This is recorded for someone to investigate. It does not change the assistant on its own.') +
					'</p>',
			},
		],
		primary_action_label: __('Report'),
		primary_action: values => {
			d.hide();
			frappe.call({
				method: 'isoft_business_ai.api.flag_answer',
				args: {
					message: messageName,
					verdict: values.verdict,
					comment: values.comment || null,
				},
				callback: r => {
					if (!r.message || !r.message.ok) return;
					if ($button) {
						$button.addClass('is-done').find('span').text(__('Reported'));
						$button.prop('disabled', true);
					}
					frappe.show_alert({ message: __('Reported. Thank you.'), indicator: 'green' }, 4);
				},
			});
		},
	});
	d.show();
};

/* ------------------------------------------------------------ row context menu */

/** A small contextual menu anchored to a button. Closes on any outside click. */
IBAI.rowMenu = function ($button, entries) {
	$('.ibai-menu').remove();
	const $menu = $('<div class="ibai-menu"></div>');
	entries.forEach(e => {
		$('<button type="button"></button>')
			.addClass(e.danger ? 'danger' : '')
			.text(e.label)
			.on('click', ev => { ev.stopPropagation(); $menu.remove(); e.run(); })
			.appendTo($menu);
	});
	$menu.appendTo(document.body);

	const r = $button[0].getBoundingClientRect();
	const h = $menu.outerHeight();
	$menu.css({
		top: Math.min(r.bottom + 4, window.innerHeight - h - 8) + 'px',
		left: Math.max(8, r.right - $menu.outerWidth()) + 'px',
	});
	$menu.find('button').first().focus();

	// A fixed-position menu has to go away on any click, any Escape and any
	// scroll of the list behind it, or it floats detached from its row.
	const close = () => {
		$menu.remove();
		$(document).off('.ibaimenu');
		$button.closest('.ibai-hlist, .ibai-stream').off('scroll.ibaimenu');
		$button.focus();
	};
	setTimeout(() => {
		$(document).on('click.ibaimenu', close);
		$(document).on('keydown.ibaimenu', ev => { if (ev.key === 'Escape') close(); });
		$button.closest('.ibai-hlist, .ibai-stream').on('scroll.ibaimenu', close);
	}, 0);
	$menu.find('button').on('click', () => {
		$(document).off('.ibaimenu');
		$button.closest('.ibai-hlist, .ibai-stream').off('scroll.ibaimenu');
	});
	return $menu;
};

/* -------------------------------------------------------------------- help */

/**
 * What the assistant is for, in the words a manager would use. Kept here
 * rather than in either surface's own script because a desk Page script is
 * cached in localStorage with no version check: this file is rebuilt and
 * cache-busted on every deploy, that one can sit stale in a browser for weeks.
 */
IBAI.helpSections = function () {
	return [
		{
			title: __('What it is'),
			body: __('Ask about your ERP in your own words, in English or Portuguese. ' +
				'It reads your data and answers with the figures behind the answer. ' +
				'It never changes anything, and it only ever sees what your own ' +
				'permissions let you see.'),
		},
		{
			title: __('What you can ask'),
			list: [
				__('Sales — totals, by customer, by item, by month, best and worst sellers'),
				__('Money — who owes you, what you owe, aged balances, cash position'),
				__('Buying — purchases by supplier or item, open orders, committed spend'),
				__('Stock — what is on hand, by warehouse, slow movers, negative stock'),
				__('Accounting — trial balance, ledgers, account statements'),
				__('A document — open an invoice, order or item and read it'),
			],
		},
		{
			title: __('Point at a record'),
			body: __('Start typing a type and pick it from the list — write "su" and ' +
				'choose Supplier@, then type the name. Portuguese works too: ' +
				'cliente@, fornecedor@, artigo@. The record is then part of the ' +
				'question, so you do not have to spell its code.'),
		},
		{
			title: __('Keep going'),
			body: __('Follow-ups are short. "And last year?" changes the period. ' +
				'Naming another customer asks the same question about them. ' +
				'You do not need to repeat yourself.'),
		},
		{
			title: __('Where the numbers come from'),
			body: __('Every answer shows the query behind it, and totals are worked ' +
				'out in the database, never added up by the assistant. If it cannot ' +
				'find something it says so rather than guessing.'),
		},
		{
			title: __('Looking outside your ERP'),
			body: __('When web research is switched on, it can also look things up ' +
				'on the public web — what an unfamiliar part number is, what a ' +
				'company does, who could supply something, recent news — and will ' +
				'show a picture where it finds one. Anything from outside always ' +
				'carries its source, and is never mixed into your own figures.'),
		},
		{
			title: __('If an answer looks wrong'),
			body: __('Use Report under the answer. It records the question and the ' +
				'queries that ran, so it can be checked.'),
		},
	];
};

IBAI.helpPanel = function (onClose) {
	const $panel = $('<aside class="ibai-help" role="dialog" aria-label="' +
		IBAI.esc(__('About the ISOFT Business Assistant')) + '"></aside>');
	const $top = $('<div class="ibai-help-top"></div>').appendTo($panel);
	$('<span class="ibai-help-mark"></span>').html(IBAI.galaxy(18)).appendTo($top);
	$('<span class="ibai-help-title"></span>').text(__('How to use this')).appendTo($top);
	$('<button class="ibai-ico ibai-help-close"></button>')
		.attr('aria-label', __('Close'))
		.html(IBAI.icon('<path d="M18 6 6 18M6 6l12 12"/>'))
		.on('click', onClose)
		.appendTo($top);

	const $body = $('<div class="ibai-help-body"></div>').appendTo($panel);
	IBAI.helpSections().forEach(s => {
		const $s = $('<section class="ibai-help-sec"></section>');
		$('<h4></h4>').text(s.title).appendTo($s);
		if (s.body) $('<p></p>').text(s.body).appendTo($s);
		if (s.list) {
			const $ul = $('<ul></ul>');
			s.list.forEach(li => $('<li></li>').text(li).appendTo($ul));
			$ul.appendTo($s);
		}
		$s.appendTo($body);
	});
	return $panel;
};

/**
 * Put a "?" next to the other header buttons on whichever surface is on
 * screen, and open the panel beside the conversation rather than over it.
 */
IBAI.mountHelp = function (root) {
	const $root = $(root);
	// The two surfaces build different headers: the quick panel has a row of
	// icon buttons, the workspace a bar above the conversation.
	const $actions = $root.find('.ibai-head-actions, .ibai-main-top').first();
	if (!$actions.length || $actions.find('.ibai-act-help').length) return;
	const first = $actions.hasClass('ibai-head-actions');

	const inConsole = $root.hasClass('ibai-console');
	let $panel = null;
	let watcher = null;
	let gone = null;

	// Appended to the body, not inside the surface: the quick panel clips its
	// children, so a panel hung off its left edge was built, measured as
	// visible, and painted nowhere. Positioned against the surface's own box
	// instead, which also survives the panel being dragged wider.
	// The help lives on the body, not inside the surface, so nothing takes it
	// away when the surface goes: closing the agent left its own instructions
	// hanging over the desk.
	const stillThere = () => document.body.contains($root[0])
		&& ($root.hasClass('ibai-console') || $root.hasClass('is-open'));

	const place = () => {
		if (!$panel) return;
		if (!stillThere()) { close(); return; }
		const r = $root[0].getBoundingClientRect();
		const gap = 12;
		const width = Math.min(inConsole ? 360 : 320,
			Math.max(260, (inConsole ? r.width : r.left) - gap * 2));
		if (window.innerWidth <= 900) {
			$panel.css({top: r.top, left: r.left, width: r.width, height: r.height});
			return;
		}
		$panel.css(inConsole
			? {top: r.top + gap, left: r.right - width - gap, width: width,
			   height: Math.max(220, r.height - gap * 2)}
			: {top: r.top, left: Math.max(gap, r.left - width - gap), width: width,
			   height: r.height});
	};

	const close = () => {
		if (watcher) { try { watcher.disconnect(); } catch (e) { /* ignore */ } watcher = null; }
		if (gone) { try { gone.disconnect(); } catch (e) { /* ignore */ } gone = null; }
		$(window).off('resize.ibaihelp scroll.ibaihelp');
		if ($panel) { $panel.remove(); $panel = null; }
		$btn.attr('aria-expanded', 'false');
	};
	const open = () => {
		$panel = IBAI.helpPanel(close)
			.addClass(inConsole ? 'in-console' : 'in-panel')
			.appendTo(document.body);
		place();
		$(window).on('resize.ibaihelp scroll.ibaihelp', place);
		try {
			watcher = new ResizeObserver(place);
			watcher.observe($root[0]);
		} catch (e) { /* no observer: resize still repositions it */ }
		try {
			// The quick panel closes by dropping a class rather than by being
			// removed, which resizing alone never notices.
			gone = new MutationObserver(place);
			gone.observe($root[0], {attributes: true, attributeFilter: ['class']});
			gone.observe(document.body, {childList: true});
		} catch (e) { /* ignore */ }
		$btn.attr('aria-expanded', 'true');
	};
	const $btn = $('<button class="ibai-ico ibai-act-help"></button>')
		.attr('aria-label', __('How to use this'))
		.attr('title', __('How to use this'))
		.attr('aria-expanded', 'false')
		.html(IBAI.icon('<circle cx="12" cy="12" r="9"/>' +
			'<path d="M9.2 9a2.8 2.8 0 0 1 5.5.7c0 1.9-2.7 2.3-2.7 4"/>' +
			'<path d="M12 17.5h.01"/>'))
		.on('click', () => { if ($panel) { close(); } else { open(); } });
	// First among the panel's icons, because it is the one a newcomer needs and
	// the rest manage a conversation they have not started yet. Last in the
	// workspace bar, which reads left to right into the conversation.
	if (first) { $actions.prepend($btn); } else { $actions.append($btn); }
};

/**
 * Both surfaces build their own header, and one of them ships in a cached
 * Page script, so the button installs itself whenever a surface turns up.
 */
IBAI.watchHelp = function () {
	const scan = () => {
		$('.ibai-panel, .ibai-console').each(function () { IBAI.mountHelp(this); });
	};
	scan();
	try {
		new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
	} catch (e) {
		setInterval(scan, 1500);
	}
};

$(() => IBAI.watchHelp());
