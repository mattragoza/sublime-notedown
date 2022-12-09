import sys, os
from collections import defaultdict
import datetime as dt
import webbrowser

import sublime
import sublime_plugin


HOME_FILE = 'README.md'

URL_SELECTOR = 'markup.underline.link'
NOTE_SELECTOR = 'text.html.markdown-wiki'
WIKI_SELECTOR = 'constant.other.wikilink.markdown-wiki'

NOTE_EXTS = {'.md'}
NAME_SEP = '__'
NOTE_TEMPLATE = '# {}\n[[{}]]\n'

NOTE_CACHE = {} # {home_dir: (mod_time, {note_name: note_files})}
BACK_LINKS = {} # {view_id: note_name}


def today():
    return dt.datetime.today().strftime('%Y-%m-%d')


def find_home_file(curr_dir):
    home_file = os.path.join(curr_dir, HOME_FILE)
    if os.path.isfile(home_file):
        return home_file
    parent_dir = os.path.dirname(curr_dir)
    if parent_dir != curr_dir:
        return find_home_file(parent_dir)


def find_note_files(home_dir):
    curr_mod_time = os.stat(home_dir).st_mtime
    last_mod_time, notes = NOTE_CACHE.get(home_dir, (None, None))
    if last_mod_time == curr_mod_time: # use cache
        print('accessing note cache')
        return notes
    print('refreshing note cache')
    notes = defaultdict(list) # {note_name: note_files}
    for dir_name, sub_dirs, files in os.walk(home_dir):
        for base_name in files:
            note_name, ext = os.path.splitext(base_name)
            note_file = os.path.join(dir_name, base_name)
            if ext not in NOTE_EXTS:
                continue
            for n in note_name.split(NAME_SEP):
                notes[n.lower()].append(note_file)
    NOTE_CACHE[home_dir] = (curr_mod_time, notes)
    return notes


class NotedownCommand(sublime_plugin.TextCommand):
    '''
    A text command that is only enabled when
    a markdown note is in the view.
    '''
    def debug(self):
        print('\nNOTEDOWN')
        print('curr_name = {}'.format(self.curr_name()))
        print('curr_file = {}'.format(self.curr_file()))
        print('curr_dir  = {}'.format(self.curr_dir()))
        print('home_file = {}'.format(self.home_file()))
        print('home_dir  = {}'.format(self.home_dir()))

    def is_enabled(self):
        return self.view.match_selector(0, NOTE_SELECTOR)

    def curr_file(self):
        return self.view.file_name()

    def curr_name(self):
        return os.path.splitext(os.path.basename(self.curr_file()))[0]

    def curr_dir(self):
        return os.path.dirname(self.curr_file())

    def home_file(self):
        return find_home_file(self.curr_dir())

    def home_dir(self):
        home_file = self.home_file()
        if home_file:
            return os.path.dirname(home_file)
        return self.curr_dir()

    def find_all_notes(self):
        return find_note_files(self.home_dir())

    def find_note_names(self):
        return sorted(self.find_all_notes().keys())

    def find_notes_by_name(self, name):
        return self.find_all_notes()[name.lower()]

    def open_note_file(self, note_file):
        flags = (
            sublime.SEMI_TRANSIENT | sublime.ADD_TO_SELECTION | sublime.REPLACE_MRU
        )
        self.view.window().open_file(note_file, flags)
        return self.view.window().find_open_file(note_file)

    def open_note_by_name(self, name):
        note_files = self.find_notes_by_name(name)

        if len(note_files) > 1:
            def on_select(index):
                view_id = self.open_note_file(note_files[index]).id()
                BACK_LINKS[view_id] = self.curr_name()
            self.view.window().show_quick_panel(note_files, on_select)

        elif len(note_files) == 1:
            view_id = self.open_note_file(note_files[0]).id()
            BACK_LINKS[view_id] = self.curr_name()

        else:
            raise Exception('note does not exist, cache is stale')

    def open_note(self):
        note_names = self.find_note_names()
        def on_select(index):
            self.open_note_by_name(note_names[index])
        self.view.window().show_quick_panel(note_names, on_select)

    def open_link(self, selection):
        if selection.empty():
            selection = self.view.extract_scope(selection.begin())
        text = self.view.substr(selection)

        if self.view.match_selector(selection.begin(), URL_SELECTOR):
            print('selected a web link: ' + repr(text))
            webbrowser.open(url=text)

        elif self.view.match_selector(selection.begin(), WIKI_SELECTOR):
            print('selected a wiki link: ' + repr(text))
            self.open_note_by_name(name=text)

        else:
            raise Exception('selection is not a link: ' + repr(text))


class NotedownPasteLinkCommand(NotedownCommand):
    '''
    A command that pastes a link at the selection.
    '''
    def run(self, edit):
        link = '[[{}]]'.format(self.link_name())
        for selection in self.view.sel():
            self.view.replace(edit, selection, link)


class NotedownPasteJournalLinkCommand(NotedownPasteLinkCommand):
    '''
    A command that pastes a link to today's journal entry.
    '''
    def link_name(self):
        return today()


class NotedownPasteBackLinkCommand(NotedownPasteLinkCommand):
    '''
    A command that pastes a backlink, i.e. a link to the
    note containing the link that was opened.
    '''
    def link_name(self):
        return BACK_LINKS[self.view.id()]


class NotedownOpenNoteCommand(NotedownCommand):
    '''
    A command that browses all notes and selects one to open.
    '''
    def run(self, edit):
        self.open_note()


class NotedownOpenLinkCommand(NotedownCommand):
    '''
    A command that opens a link (url or wiki).
    '''
    def run(self, edit):
        for selection in self.view.sel():
            self.open_link(selection)
