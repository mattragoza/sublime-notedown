"""Sublime Text Notedown plugins

Design philosophy
-----------------

- Minimalism, simplicity, and speed.
- Do nothing that conflicts with the design philosophy of Sublime Text.
- Orthogonal to Markdown and HTML.

Debugging
---------

Enable debug output from the Sublime Text console with:

    >>> import Notedown
    >>> Notedown.notedown.debug()

Design decisions
----------------

Why Markdown? It's popular, provides a "good enough" structure and syntax for
notes, provides syntax highlighting for improved readability, and it provides
heading navigation (with Command + R).

Why the [[Note name]] syntax? 1) Avoids conflict with Markdown or HTML syntax,
2) distinguishable from normal prose, 3) easy to read, and 4) efficient to
parse. Additionally, this syntax is used in other popular note-taking apps
such as Notational Velocity and Bear notes.

Why not WikiWord links? 1) You can get false matches with names from code
and ordinary prose, 2) parsing is less efficient, and 3) auto-completion is
less useful.

Why tilde (~) to separate note titles? Need a character that does not
clash with typical note titles (rules out - , .) and can be used on all
operating systems (rules out |).

Only support a single flat directory of notes because this is simple, fast,
and requires no configuration. I believe notes should be a flat concept
anyway. Perhaps tags can be supported one day.
"""

import fnmatch
import functools
import os
import re
import sys
import timeit
import webbrowser

import sublime
import sublime_plugin

_MARKDOWN_EXTENSIONS = {'.md', '.mdown', '.markdown', '.markdn'}

_DEFAULT_EXTENSION = 'md'

_URL_SELECTOR = 'markup.underline.link'

_NOTE_TEMPLATE = """\
# {}

See also:

- [[{}]]
"""


def _log_duration(f):
    def wrapper(*args, **kwargs):
        started = timeit.default_timer()
        value = f(*args, **kwargs)
        _debug_log('{:.3f}s to {}'.format(
            timeit.default_timer() - started,
            f.__name__.strip('_').replace('_', ' ')))
        return value
    return wrapper


class _NotedownTextCommand(sublime_plugin.TextCommand):

    def is_enabled(self):
        return _viewing_a_note(self.view)

    def is_visible(self):
        return _viewing_a_note(self.view)


class NotedownOpenCommand(_NotedownTextCommand):

    def run(self, edit):
        self._notes = _find_notes(self.view)
        self._link_regions = _find_link_regions(self.view)
        for selection in self.view.sel():
            if selection.empty():
                self._open_point(selection.begin())
            else:
                self._open_selection(self.view.substr(selection))

    def _open_point(self, point):
        if self.view.match_selector(point, _URL_SELECTOR):
            webbrowser.open(self.view.substr(self.view.extract_scope(point)))
        else:
            title = self._title_at_point(point)
            if title:
                self._open_note(title)

    def _open_selection(self, text):
        self._open_note(text)

    def _open_note(self, title):
        try:
            filenames = [x for _, x in self._notes[title.lower()]]
        except KeyError:
            filename = _create_note(title, self.view)
            if filename:  # Not cancelled
                self._open_file(filename)
            return

        if len(filenames) > 1:
            def on_done(index):
                if index != -1:  # Not cancelled
                    self._open_file(filenames[index])
            self.view.window().show_quick_panel(filenames, on_done)
        else:
            self._open_file(filenames.pop())

    def _open_file(self, filename):
        self.view.window().open_file(filename)

    def _title_at_point(self, point):
        for region in self._link_regions:
            if region.contains(point):
                return self.view.substr(region)[2:-2]
        return self.view.substr(self.view.word(point))


class NotedownLintCommand(_NotedownTextCommand):

    def run(self, edit):
        self.errors = []  # [(description, region, edit_region)]
        self._notes = _find_notes(self.view)
        self._check_note_title()
        self._find_broken_links()
        self._highlight_errors()
        self._show_error_list()

    def _check_note_title(self):
        if not _note_title(self.view):
            self.errors.append(
                ('Invalid note title (must start with #)',
                 self.view.line(0), sublime.Region(0, 0)))

    def _find_broken_links(self):
        for region in _find_link_regions(self.view):
            text_region = sublime.Region(region.begin() + len('[['),
                                         region.end() - len(']]'))
            if self.view.substr(text_region).lower() not in self._notes:
                self.errors.append(('Missing note file', region, text_region))

    def _highlight_errors(self):
        self.view.add_regions('notedown',
                              [region for _, region, _ in self.errors],
                              'invalid.illegal', '', sublime.DRAW_NO_FILL)

    def _show_error_list(self):
        self.view.window().show_quick_panel(
            [self._format_error(x) for x in self.errors],
            self._on_error_selected)

    def _format_error(self, error):
        description, region, _ = error
        row, _ = self.view.rowcol(region.begin())
        text = self.view.substr(region)
        return [description, 'Line {}: {}'.format(row + 1, text)]

    def _on_error_selected(self, index):
        if index == -1:  # Canceled
            return
        _, region, edit_region = self.errors[index]
        self.view.sel().clear()
        self.view.sel().add(edit_region)
        self.view.show(self.view.sel())


class NotedownEventListener(sublime_plugin.EventListener):

    def on_pre_close(self, view):
        if view.is_primary():  # Only one view on buffer
            try:
                del _link_regions_cache[view.buffer_id()]
            except KeyError:
                pass

    def on_post_save_async(self, view):
        if not _viewing_a_note(view):
            return

        renamed = self._reflect_title_in_filename(view)
        if not renamed:
            view.run_command('notedown_lint')

    def on_query_completions(self, view, prefix, locations):
        if not _viewing_a_note(view):
            return False

        if not self._can_show_completions(view, locations):
            return

        file_name = view.file_name()
        titles = {y for x in _find_notes(view).values() for y, z in x
                  if not os.path.samefile(z, file_name)}
        return [[x + '\tNote', x + ']]'] for x in sorted(titles)]

    def _can_show_completions(self, view, locations):
        # Show completions if not in raw scope and [[ has been typed.
        point = locations[0]
        if view.match_selector(point, 'markup.raw'):
            return False
        pre_text = view.substr(sublime.Region(view.line(point).begin(),
                                              point))
        if not re.match(r'.*\[\[(.*?)(?!\]\])', pre_text):
            return False
        return True

    def _reflect_title_in_filename(self, view):
        """Returns True if the file was renamed."""
        title = _note_title(view)
        if not title:
            return False

        old_title, ext = os.path.splitext(os.path.basename(view.file_name()))
        if title == old_title:
            return False

        new_filename = title + ext
        text = 'Rename this file to {}?'.format(new_filename)
        if not sublime.ok_cancel_dialog(text, 'Rename File'):
            return False

        old_filename = view.file_name()
        new_filename = os.path.join(os.path.dirname(old_filename),
                                    new_filename)

        window = view.window()
        try:
            os.rename(old_filename, new_filename)
        except OSError as exp:
            sublime.error_message('Could not rename {}:\n\n{}'
                                  .format(old_filename, exp))
            return False
        view.close()
        window.open_file(new_filename)

        return True


def debug(enable=True):
    global _debug_enabled
    _debug_enabled = enable


def _note_title(view):
    """Returns the title of the note in view or None if there is no title."""
    if not view.match_selector(0, 'markup.heading.1.markdown'):
        return None
    return view.substr(view.line(0))[2:].strip()


@_log_duration
def _find_notes(view):
    """Returns a {<lowercase title>: [(<title>, <filename>)]} dictionary
    representing the notes in the directory containing the file shown in view.

    Results are cached in _notes_cache.
    """
    path = os.path.dirname(view.file_name())

    mtime, notes = _notes_cache.get(path, (None, None))
    if mtime == os.stat(path).st_mtime:
        return notes

    notes = {}
    for name in os.listdir(path):
        titles = _parse_filename(name)
        if titles:
            filename = os.path.join(path, name)
            for lower_title, title in titles:
                if lower_title in notes:
                    notes[lower_title].append((title, filename))
                else:
                    notes[lower_title] = [(title, filename)]
    _notes_cache[path] = os.stat(path).st_mtime, notes
    return notes


@functools.lru_cache(maxsize=2 ** 16)
def _parse_filename(filename):
    """Returns a list of (<lower case title>, <title>) 2-tuples."""
    base, ext = os.path.splitext(filename)
    if ext not in _MARKDOWN_EXTENSIONS:
        return []
    return [(x.lower(), x) for x in (y.strip() for y in base.split('~'))]


def _create_note(title, view):
    """Creates a new note.

    Returns the filename of the new note or None if the user canceled or
    there was an error.
    """
    basename = '{}.{}'.format(title, _setting('markdown_extension', str,
                                              _DEFAULT_EXTENSION))
    text = 'Do you want to create {}?'.format(basename)
    if not sublime.ok_cancel_dialog(text, 'Create File'):
        return
    filename = os.path.join(os.path.dirname(view.file_name()), basename)

    back_titles = _parse_filename(os.path.basename(view.file_name()))
    primary_back_title = back_titles[0][1]
    try:
        with open(filename, 'w') as fileobj:
            fileobj.write(_NOTE_TEMPLATE.format(title, primary_back_title))
    except IOError as exp:
        sublime.error_message('Could not create {}:\n\n{}'
                              .format(filename, exp))
        return

    return filename


@_log_duration
def _find_link_regions(view):
    """Returns a list of sublime.Region objects describing link locations
    within a Markdown file.

    Results are cached in _link_regions_cache.
    """
    last_change_count, regions = _link_regions_cache.get(view.buffer_id(),
                                                         (None, None))
    if view.change_count() == last_change_count:
        return regions

    regions = [x for x in view.find_all(r'\[\[.+?\]\]')
               if not view.match_selector(x.begin(), 'markup.raw')]
    _link_regions_cache[view.buffer_id()] = view.change_count(), regions
    return regions


def _viewing_a_note(view):
    if not view.match_selector(0, 'text.html.markdown'):
        return False

    note_folder_patterns = _setting('note_folder_patterns', list)
    if not note_folder_patterns:
        return True
    if any(not isinstance(x, str) for x in note_folder_patterns):
        _invalid_setting('note_folder_patterns', note_folder_patterns,
                         '[str, ...]')
        return False

    note_folder = os.path.basename(os.path.dirname(view.file_name()))
    return any(fnmatch.fnmatch(note_folder, x) for x in note_folder_patterns)


def _setting(name, type_, default=None):
    value = sublime.load_settings('Notedown.sublime-settings').get(name,
                                                                   default)
    if value is not default and not isinstance(value, type_):
        _invalid_setting(name, value, type_)
        return default
    else:
        return value


def _invalid_setting(name, value, type_):
    sublime.error_message('Invalid Notedown setting "{}":\n\n{!r}\n\n'
                          'Must be of type {}.'.format(name, value, type_))


def _debug_log(message):
    if _debug_enabled:
        _log(message)


def _log(message):
    sys.stdout.write('Notedown: {}\n'.format(message))
    sys.stdout.flush()


_debug_enabled = False
_notes_cache = {}             # {path: (mtime, notes dict)}
_link_regions_cache = {}      # {buffer id: (change count, regions)}
