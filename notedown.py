"""Sublime Text Notedown"""

import fnmatch
import os
import re
import sys
import timeit
import webbrowser
import datetime as dt
from collections import defaultdict

import sublime
import sublime_plugin

try:
    sys.path.append(
        'C:\\Users\\mtr22\\Code\\Miniconda3\\envs\\sublime\\lib\\site-packages'
    )
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import linear_kernel
except ImportError as e:
    print(e, file=sys.stderr)

_MARKDOWN_EXTENSIONS = {'.md', '.mdown', '.markdown', '.markdn'}

_DEFAULT_EXTENSION = 'md'

_URL_SELECTOR = 'markup.underline.link'

_TITLE_SEP = '~'

_NOTE_TEMPLATE = """\
# {}
[[{}]]

"""

_HOME_NAME = 'README'
_LAST_NOTE = _HOME_NAME

_STOP_WORDS = {
    'the', 'a', 'an', 'to', 'is', 'of', 'that', 'we', 'are', 'for', 'no',
    'about', 'in', 'this', 'and', 'from', 'it', 'try', 'where', 'need',
    'with', 'what', 'on', 'use', 'as', 'they', 'each', 'more', 'not', 'i',
    'was', 'will', 'be', 'their', 'can', 'could', 'would', 'part', 'done',
    'very', 'by', 'many', 'put', 'than', 'also', 'were', 'these', 'how'
}


def _log_duration(f):
    """Decorator for logging the duration of a function call."""
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


class NotedownPasteLinkCommand(_NotedownTextCommand):

    def run(self, edit):
        link = '[[{}]]'.format(self.get_note())
        for selection in self.view.sel():
            if selection.empty():
                self.view.insert(edit, selection.begin(), link)
            else:
                self.view.replace(edit, selection, link)


class NotedownPasteJournalLinkCommand(NotedownPasteLinkCommand):

    def get_note(self):
        return today()


class NotedownPasteBackLinkCommand(NotedownPasteLinkCommand):

    def get_note(self):
        return _LAST_NOTE


class NotedownOpenLinkCommand(_NotedownTextCommand):

    def is_enabled(self):
        return super().is_enabled() and not all(s.empty() for s in self.view.sel())

    def run(self, edit):
        self._notes = _find_notes_for_view(self.view)
        _debug_log('num notes: {}'.format(len(self._notes)))
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
            filenames = [_full_path(self.view, x)
                         for _, x in self._notes[title.lower()]]
        except KeyError:
            filename = _create_note(title, self.view)
            if filename:  # Not canceled
                self._open_file(filename)
            return

        if len(filenames) > 1:
            def on_done(index):
                if index != -1:  # Not canceled
                    self._open_file(filenames[index])
            self.view.window().show_quick_panel(filenames, on_done)
        else:
            self._open_file(filenames.pop())

        # store the backlink
        global _LAST_NOTE
        curr_file = self.view.file_name()
        curr_name = os.path.splitext(os.path.basename(curr_file))[0]
        _LAST_NOTE = curr_name

    def _open_file(self, filename):
        flags = (
            sublime.SEMI_TRANSIENT |
            sublime.ADD_TO_SELECTION |
            sublime.REPLACE_MRU
        )
        self.view.window().open_file(filename, flags)

    def _title_at_point(self, point):
        for region in self._link_regions:
            if region.contains(point):
                return self.view.substr(region)[2:-2]
        return self.view.substr(self.view.word(point))


def today():
    return dt.datetime.today().strftime('%Y-%m-%d')


class NotedownOpenJournalCommand(NotedownOpenCommand):

    def run(self, edit):
        self._notes = _find_notes_for_view(self.view)
        self._open_note(today())


class NotedownFindSimilarNotesCommand(NotedownOpenCommand):
    '''
    Use cosine similarity between tf-idf
    vectors to find similar notes.
    '''
    def run(self, edit):

        # get names and paths to notes
        notes = _find_notes_for_view(self.view)
        note_names = list(notes.keys())
        note_files = [n[0][1] for n in notes.values()]
        note_index = {n: i for i, n in enumerate(notes)}

        # read and process notes into tf-idf vectors
        model = TfidfVectorizer(input='filename', stop_words=_STOP_WORDS)
        note_vecs = model.fit_transform(note_files).toarray()

        # get name and vector of current note to use as query
        curr_file = self.view.file_name()
        curr_name = os.path.splitext(os.path.basename(curr_file))[0]
        curr_vec = note_vecs[note_index[curr_name.lower()]]

        # compute cosine similarity between notes
        sim = linear_kernel(curr_vec, note_vecs)[0]
        idx = np.argsort(-sim)

        # rank the similar terms for each note
        terms = model.get_feature_names()
        term_sim = curr_vec*note_vecs
        term_idx = np.argsort(-term_sim, axis=1)
        note_terms = [
            [terms[j] for j in t[:10] if note_vecs[i,j] > 0]
                for i, t in enumerate(term_idx)
        ]

        sim_files = [note_files[i] for i in idx]
        sim_menu = [
            '[{:.3f}] {} ({})'.format(
                sim[i], note_names[i], ', '.join(note_terms[i])
            ) for i in idx[:100]
        ]

        # show the files sorted by similarity
        def on_done(index):
            if index != -1: # Not canceled
                self._open_file(sim_files[index])
        self.view.window().show_quick_panel(sim_menu, on_done)


class NotedownConvertFileLinksCommand(_NotedownTextCommand):

    def run(self, edit):
        print('converting file links')
        self._notes = _find_notes_for_view(self.view)
        for k, v in self._notes.items():
            self.convert_links(v[0][1])
        print('done')

    def convert_links(self, note_file):
        print('note:', note_file)
        with open(note_file, encoding='utf-8') as f:
            buf = f.read()
        f = self.convert_link
        buf = re.sub(r'\[(.+?)\]\((.+?)\)', f, buf)
        with open(note_file, 'w', encoding='utf-8') as f:
            f.write(buf)

    def convert_link(self, m):
        name = m.group(1)
        try:
            self._notes[name.lower()]
            return '[[{}]]'.format(name)
        except KeyError:
            return m.group()


class NotedownConvertWikiLinksCommand(_NotedownTextCommand):

    def run(self, edit):
        print('converting wiki links')
        self._notes = _find_notes_for_view(self.view)
        for k, v in self._notes.items():
            self.convert_links(v[0][1])
        print('done')

    def convert_links(self, note_file):
        print('note:', note_file)
        with open(note_file, encoding='utf-8') as f:
            buf = f.read()
        curr_dir = os.path.dirname(note_file)
        f = lambda m: self.convert_link(m, curr_dir)
        buf = re.sub(r'\[\[(.+?)\]\]', f, buf)
        with open(note_file, 'w', encoding='utf-8') as f:
            f.write(buf)

    def convert_link(self, m, curr_dir):
        name = m.group(1)
        try:
            abs_file = self._notes[name.lower()][0][1]
            rel_file = os.path.relpath(abs_file, curr_dir)
            rel_file = rel_file.replace(os.sep, '/')
            return '[{}]({})'.format(name, rel_file)
        except KeyError:
            return m.group()


class NotedownLintCommand(_NotedownTextCommand):

    def run(self, edit):
        errors = []  # [(description, region, edit_region)]
        self._check_note_title(errors)
        self._find_broken_links(errors)
        self._highlight_errors(errors)
        self._show_errors_in_quick_panel(errors)

    def _check_note_title(self, errors):
        if not _note_title(self.view):
            errors.append(
                ('Invalid note title; first line must be a '
                 'first-level header (start with a single #)',
                 self.view.line(0), sublime.Region(0, 0)))

    def _find_broken_links(self, errors):
        notes = _find_notes_for_view(self.view)
        for region in _find_link_regions(self.view):
            text_region = sublime.Region(region.begin() + len('[['),
                                         region.end() - len(']]'))
            if self.view.substr(text_region).lower() not in notes:
                errors.append(('Missing note file', region, text_region))

    def _highlight_errors(self, errors):
        self.view.add_regions('notedown', [region for _, region, _ in errors],
                              'invalid.illegal', '', sublime.DRAW_NO_FILL)

    def _show_errors_in_quick_panel(self, errors):
        def on_done(index):
            if index != -1:  # Not canceled
                self._goto_error(errors[index])

        self.view.window().show_quick_panel(
            [self._format_error(x) for x in errors], on_done)

    def _goto_error(self, error):
        _, region, edit_region = error
        self.view.sel().clear()
        self.view.sel().add(edit_region)
        self.view.show(self.view.sel())

    def _format_error(self, error):
        description, region, _ = error
        row, _ = self.view.rowcol(region.begin())
        text = self.view.substr(region)
        return [description, 'Line {}: {}'.format(row + 1, text)]


class NotedownClearCacheCommand(NotedownLintCommand):

    def run(self, edit):
        self.clear_cache()
        super().run(edit)

    def clear_cache(self):
        global _notes_cache
        global _link_regions_cache
        _notes_cache = {}
        _link_regions_cache = {}


class NotedownLinkCommand(_NotedownTextCommand):
    """Command to add a note link at the cursor."""

    def run(self, edit):
        file_name = self.view.file_name()
        titles = sorted(y for x in _find_notes_for_view(self.view).values()
                        for y, z in x
                        if not os.path.samefile(_full_path(self.view, z),
                                                file_name))

        def on_done(index):
            if index != -1:  # Not canceled
                self.view.run_command('notedown_place_link',
                                      {'title': titles[index]})

        selected_index = 0
        first_sel = self.view.substr(self.view.sel()[0]).lower()
        for index, title in enumerate(titles):
            if title.lower().startswith(first_sel):
                selected_index = index
                break

        self.view.window().show_quick_panel(titles, on_done, 0, selected_index)


class NotedownPlaceLinkCommand(_NotedownTextCommand):

    def run(self, edit, title):
        selection = self.view.sel()
        text = '[[{}]]'.format(title)
        for region in selection:
            self.view.replace(edit, region, text)
        regions = [sublime.Region(r.end(), r.end()) for r in selection]
        selection.clear()
        selection.add_all(regions)


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

    def _reflect_title_in_filename(self, view):
        """Returns True if the file was renamed."""
        new_name = _note_title(view)
        if not new_name:
            return False

        old_filename = view.file_name()
        old_name, ext = os.path.splitext(os.path.basename(old_filename))
        if new_name == old_name:
            return False

        new_basename = new_name + ext
        new_filename = os.path.join(os.path.dirname(old_filename),
                                    new_basename)

        text = 'Rename this file to {}?'.format(new_basename)
        if not sublime.ok_cancel_dialog(text, 'Rename File'):
            return False

        window = view.window()
        encoding = view.settings().get('default_encoding', 'utf-8')
        view.close()

        try:
            os.rename(old_filename, new_filename)


        except OSError as exp:
            sublime.error_message('Could not rename {}:\n\n{}'
                                  .format(old_filename, exp))
            return False

        view = window.open_file(new_filename)
        while view.is_loading():
            pass

        curr_dir = os.path.dirname(new_filename)
        home_dir = _find_home_dir(curr_dir)
        if home_dir in _notes_cache:
            del _notes_cache[home_dir]
        updated = self._update_backlinks(old_name, new_name, encoding,
                                         home_dir)
        view.window().status_message('Updated backlinks to {} note(s)'
                                     .format(updated))

        return True

    @_log_duration
    def _update_backlinks(self, old_name, new_name, encoding, notes_dir):
        """
        Logic:
            a -> x ~ y    replace a with x
            a -> a ~ x    do nothing
            a ~ b -> x    replace a and b with x

        Returns:
            Count of updated note files.
        """
        removed = set(_titles(old_name)) - set(_titles(new_name))
        if not removed:
            print('nothing removed')
            return  # Nothing to do
        print('trying to update backlinks')

        pattern = re.compile(r'\[\[({})\]\]'.format('|'.join(removed)),
                             re.IGNORECASE)
        repl = '[[{}]]'.format(next(_titles(new_name)))
        _debug_log('updating back links: {} -> {}'.format('|'.join(removed),
                                                          new_name))

        updated = 0
        filenames = {filename
                     for notes in _find_notes(notes_dir).values()
                     for title, filename in notes}

        for filename in filenames:
            with open(filename, encoding=encoding) as fileobj:
                try:
                    text, count = pattern.subn(repl, fileobj.read())
                except UnicodeEncodeError:
                    _log('{} is not {} encoded'.format(filename, encoding))
                    continue

            if count:
                print(filename, count)
                updated += 1
                _debug_log('updating {} back link(s) in {}'
                           .format(count, filename))
                with open(filename, 'w', encoding=encoding) as fileobj:
                    fileobj.write(text)

        return updated


def debug(enable=True):
    global _debug_enabled
    _debug_enabled = enable


def _note_title(view):
    """Returns the title of the note in view or None if there is no title."""
    if not view.match_selector(0, 'markup.heading.1.markdown'):
        return None
    return view.substr(view.line(0))[2:].strip()


def _find_home_dir_for_view(view):
    curr_dir = os.path.dirname(view.file_name())
    return _find_home_dir(curr_dir)


def _find_home_dir(curr_dir):
    home_file = os.path.join(curr_dir, _HOME_FILE_BASE)
    if os.path.isfile(home_file):
        return curr_dir
    parent_dir = os.path.dirname(curr_dir)
    if parent_dir != curr_dir:
        return _find_home_dir(parent_dir)


def _find_notes_for_view(view):
    curr_dir = os.path.dirname(view.file_name())
    home_dir = _find_home_dir(curr_dir)
    if home_dir:
        return _find_notes(home_dir)
    else:
        return _find_notes(curr_dir)


@_log_duration
def _find_notes(directory):
    """Returns a {<lowercase title>: [(<title>, <filename>)]} dict describing
    the notes in directory (and all subdirectories).

    Results are cached in _notes_cache.
    """
    mtime, notes = _notes_cache.get(directory, (None, None))
    if mtime == os.stat(directory).st_mtime:
        return notes

    notes = {}
    for dir_, sub_dirs, files in os.walk(directory):
        for base in files:
            name, ext = os.path.splitext(base)
            file_ = os.path.join(dir_, base)
            if ext not in _MARKDOWN_EXTENSIONS:
                continue
            for title in _titles(name):
                lower_title = title.lower()
                if lower_title in notes:
                    notes[lower_title].append((title, file_))
                else:
                    notes[lower_title] = [(title, file_)]

    _notes_cache[directory] = os.stat(directory).st_mtime, notes
    return notes


@_log_duration
def _create_note(title, view):
    """Creates a new note.

    Returns the filename of the new note, or None if the user canceled or
    there was an error.
    """
    ext = _setting('markdown_extension', str, _DEFAULT_EXTENSION)
    filename = '{}.{}'.format(title, ext)
    text = 'Create a new note "{}"?'.format(filename)
    if not sublime.ok_cancel_dialog(text, 'Create Note'):
        return
    filename = _full_path(view, filename)

    back_title = next(
        _titles(os.path.splitext(os.path.basename(view.file_name()))[0]))

    try:
        with open(filename, 'w') as fileobj:
            fileobj.write(_NOTE_TEMPLATE.format(title, back_title))
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


def _notes_dir(view):
    return os.path.dirname(view.file_name())


def _full_path(view, filename):
    return os.path.join(_notes_dir(view), filename)


def _titles(name):
    return (x.strip() for x in name.split(_TITLE_SEP))


def _viewing_a_note(view):
    if not view.match_selector(0, 'text.html.markdown-wiki'):
        return False

    note_folder_patterns = _setting('note_folder_patterns', list)
    if not note_folder_patterns:
        return True
    if any(not isinstance(x, str) for x in note_folder_patterns):
        _invalid_setting('note_folder_patterns', note_folder_patterns,
                         '[str, ...]')
        return False

    note_folder = _find_notes_for_view(view)
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
