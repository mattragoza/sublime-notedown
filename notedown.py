import sys, os, re, time
from collections import defaultdict
import datetime as dt
import webbrowser

import sublime
import sublime_plugin


HOME_FILE = 'README.md'

NOTE_SELECTOR = 'text.html.markdown-wiki'
HEAD_SELECTOR = 'markup.heading.1.markdown'
URL_SELECTOR = 'markup.underline.link'
WIKI_SELECTOR = 'constant.other.wikilink.markdown-wiki'

NOTE_EXTS = {'.md'}
NAME_SEP = '__'
NOTE_TEMPLATE = '# {}\n[[{}]]\n\n\n'
LINK_TEMPLATE = '[[{}]]'
DATE_FORMAT = '%Y-%m-%d'

CITE_JOURNAL_TEMPLATE = '''```bibtex
@article{name1234key,
    title={{Journal paper}},
    author={},
    journal={},
    month={},
    day={},
    year={},
    volume={},
    number={},
    pages={--},
    doi={},
    abstract={},
}
```'''
CITE_PREPRINT_TEMPLATE = '''```bibtex
@article{name1234key,
    title={{ArXiv preprint}},
    author={},
    year={},
    month={},
    day={},
    eprint={1234.12345},
    archivePrefix={arXiv},
    primaryClass={cs.LG},
    journal={arXiv preprint: 1234.12345 [cs.LG]},
    doi={},
    abstract={},
}
```'''
CITE_CONFERENCE_TEMPLATE = '''```bibtex
@inproceedings{name1234key,
    title={{Conference paper}},
    author={},
    booktitle={},
    publisher={},
    editor={},
    month={},
    day={},
    year={},
    volume={},
    number={},
    pages={--},
    series={},
    address={},
    doi={},
    abstract={},
}
```'''

NOTE_CACHE = {} # {home_dir: (mod_time, {note_name: note_files})}
BACK_LINKS = {} # {view_id: note_name}

GROUP_CACHE = {} # {sheet_id: group_id}
PRIMARY_GROUP = 3


def read_file(note_file):
    with open(note_file, encoding='utf-8') as f:
        return f.read()


def write_file(note_file, buf):
    with open(note_file, 'w', encoding='utf-8') as f:
        f.write(buf)


def today():
    return dt.datetime.today().strftime(DATE_FORMAT)


def viewing_a_note(view):
    return view.match_selector(0, NOTE_SELECTOR)


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
    if notes and last_mod_time == curr_mod_time: # use cache
        print('using note cache')
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


def create_note_file(note_file, name, backlink):
    assert not os.path.isfile(note_file), "File already exists"
    print('Creating ', repr(name), repr(backlink))
    with open(note_file, 'w') as f:
        f.write(NOTE_TEMPLATE.format(name, backlink))
    return note_file


def open_note_file(window, note_file, primary=False):
    flags = sublime.SEMI_TRANSIENT
    flags |= sublime.REPLACE_MRU
    flags |= sublime.CLEAR_TO_RIGHT
    flags |= sublime.FORCE_CLONE
    window.open_file(note_file, flags, group=PRIMARY_GROUP if primary else -1)
    return window.find_open_file(note_file)


def convert_wiki_links(note_file, notes):
    print('convert_wiki_links', note_file)
    buf = read_file(note_file)
    curr_dir = os.path.dirname(note_file)
    f = lambda m: convert_wiki_link(m, curr_dir, notes)
    buf = re.sub(r'\[\[([^\[\]]+?)\]\]', f, buf)
    write_file(note_file, buf)


def convert_file_links(note_file, notes):
    print('convert_file_links', note_file)
    buf = read_file(note_file)
    f = lambda m: convert_file_link(m, notes)
    buf = re.sub(r'\[([^\[\]]+?)\]\((.+?)\)', f, buf)
    write_file(note_file, buf)


def convert_wiki_link(m, curr_dir, notes):
    name = m.group(1).lower()
    if name in notes:
        abs_file = notes[name][0]
        rel_file = os.path.relpath(abs_file, curr_dir)
        rel_file = rel_file.replace(os.sep, '/')
        print(name, abs_file)
        return '[{}]({})'.format(m.group(1), rel_file)
    else:
        print(name, 'not found')
        return m.group()


def convert_file_link(m, notes):
    name = m.group(1)
    if name.lower() in notes:
        print(name, 'found')
        return '[[{}]]'.format(name)
    else:
        print(name, 'not found')
        return m.group()


class NotedownView(object):
    '''
    A view into a notedown file.
    '''
    def __init__(self, view):
        self.view = view

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

    def debug(self):
        print('\nNOTEDOWN')
        print('curr_name = {}'.format(self.curr_name()))
        print('curr_file = {}'.format(self.curr_file()))
        print('curr_dir  = {}'.format(self.curr_dir()))
        print('home_file = {}'.format(self.home_file()))
        print('home_dir  = {}'.format(self.home_dir()))

    def find_all_notes(self):
        return find_note_files(self.home_dir())

    def find_notes_by_name(self, name):
        return self.find_all_notes()[name.lower()]

    def list_all_notes(self):
        return sorted(self.find_all_notes().keys())

    def create_note_file(self, name):
        note_file = os.path.join(self.curr_dir(), '{}.md'.format(name))
        text = 'Create new note {}?'.format(repr(name))
        if sublime.ok_cancel_dialog(text, 'Create note'):
            try:
                return create_note_file(note_file, name, self.curr_name())
            except IOError as e:
                sublime.error_message('Failed to create {}:\n{}'.format(note_file, e))

    def open_note_file(self, note_file, primary):
        return open_note_file(self.view.window(), note_file, primary)

    def open_note_by_name(self, name, primary):
        note_files = self.find_notes_by_name(name)

        if len(note_files) > 1: # multiple notes match
            def on_select(index):
                if index != -1:
                    return self.open_note_file(note_files[index], primary).id()
            return self.view.window().show_quick_panel(note_files, on_select)

        elif len(note_files) == 1: # single note match
            return self.open_note_file(note_files[0], primary).id()

        else: # create new note
            note_file = self.create_note_file(name)
            if note_file is not None:
                return self.open_note_file(note_file, primary).id()

    def get_head_region(self):
        if self.view.match_selector(0, HEAD_SELECTOR):
            return self.view.extract_scope(2)
        return sublime.Region(0, 1)

    def curr_head(self):
        return self.view.substr(self.get_head_region())

    def find_link_regions(self):
        return self.view.find_by_selector(WIKI_SELECTOR)

    def convert_wiki_links(self):
        notes = self.find_all_notes()
        for name, note_files in notes.items():
            for note_file in note_files:
                convert_wiki_links(note_file, notes)

    def convert_file_links(self):
        notes = self.find_all_notes()
        for name, note_files in notes.items():
            for note_file in note_files:
                convert_file_links(note_file, notes)


class NotedownTextCommand(sublime_plugin.TextCommand):
    '''
    A text command that is only enabled when
    a markdown note is in the view.
    '''
    def is_enabled(self):
        return viewing_a_note(self.view)


class NotedownOpenNoteCommand(NotedownTextCommand):
    '''
    A command that browses all notes and selects one to open.
    '''
    def run(self, edit):
        note_view = NotedownView(self.view)
        note_names = note_view.list_note_names()
        def on_select(index):
            if index != -1:
                note_view.open_note_by_name(note_names[index], primary=False)
        self.view.window().show_quick_panel(note_names, on_select)


class NotedownOpenLinkCommand(NotedownTextCommand):
    '''
    A command that opens a link (url or wiki).
    '''
    def run(self, edit, primary):
        for selection in self.view.sel():
            self.open_link(edit, selection, primary)

    def open_link(self, edit, selection, primary):
        if selection.empty():
            selection = self.view.extract_scope(selection.begin())
        link_text = self.view.substr(selection)

        if self.view.match_selector(selection.begin(), URL_SELECTOR):
            print('selected a web link: ' + repr(link_text))
            webbrowser.open(url=link_text)

        elif self.view.match_selector(selection.begin(), WIKI_SELECTOR):
            print('selected a wiki link: ' + repr(link_text))
            NotedownView(self.view).open_note_by_name(name=link_text, primary=primary)

        else: # create a new link (if a note is opened)
            if NotedownView(self.view).open_note_by_name(
                name=link_text, primary=primary
            ):
                print('creating a new link: ' + repr(link_text))
                self.create_link(edit, selection, name=link_text)

    def create_link(self, edit, selection, name):
        self.view.replace(edit, selection, LINK_TEMPLATE.format(name))


class NotedownOpenJournalCommand(NotedownTextCommand):
    '''
    A command that opens today's journal entry.
    '''
    def run(self, edit):
        note_view = NotedownView(self.view)
        note_view.open_note_by_name(today(), primary=True)


class NotedownLinkToJournalCommand(NotedownTextCommand):
    '''
    A command that pastes a link to today's journal entry.
    '''
    def run(self, edit):
        link = LINK_TEMPLATE.format(today())
        for selection in self.view.sel():
            self.view.replace(edit, selection, link)


class NotedownCiteJournalCommand(NotedownTextCommand):

    def run(self, edit):
        text = CITE_JOURNAL_TEMPLATE
        for selection in self.view.sel():
            self.view.replace(edit, selection, text)


class NotedownCitePreprintCommand(NotedownTextCommand):

    def run(self, edit):
        text = CITE_PREPRINT_TEMPLATE
        for selection in self.view.sel():
            self.view.replace(edit, selection, text)


class NotedownCiteConferenceCommand(NotedownTextCommand):

    def run(self, edit):
        text = CITE_CONFERENCE_TEMPLATE
        for selection in self.view.sel():
            self.view.replace(edit, selection, text)


class NotedownListBackLinksCommand(NotedownTextCommand):
    '''
    A command that creates a list of links to other
    notes that link to the current note.
    '''
    def run(self, edit):
        note_view = NotedownView(self.view)
        names = note_view.curr_name().split(NAME_SEP)
        pattern = re.compile(r'\[\[({})\]\]'.format('|'.join(names)))
        encoding = self.view.settings().get('default_encoding', 'utf-8')
        notes = note_view.find_all_notes()
        note_files = {n for ns in notes.values() for n in ns}
        back_links = []
        for note_file in note_files:
            with open(note_file, encoding=encoding) as f:
                try:
                    match = pattern.search(f.read())
                except UnicodeEncodeError:
                    print('{} is not {} encoded'.format(note_file, encoding))
                    continue
                if match:
                    link_name = os.path.splitext(os.path.basename(note_file))[0]
                    back_links.append(link_name)

        text = ' '.join(['[[{}]]'.format(l) for l in sorted(back_links)])
        for selection in self.view.sel():
            self.view.replace(edit, selection, text)


class NotedownConvertWikiLinksCommand(NotedownTextCommand):

    def run(self, edit):
        NotedownView(self.view).convert_wiki_links()


class NotedownConvertFileLinksCommand(NotedownTextCommand):

    def run(self, edit):
        NotedownView(self.view).convert_file_links()


class NotedownSetPrimaryGroupCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        global PRIMARY_GROUP
        PRIMARY_GROUP = self.view.sheet().group()
        print(PRIMARY_GROUP)


class NotedownToggleFocusCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        window = self.view.window()
        sheet = self.view.sheet()
        if sheet.is_transient():
            return
        curr_group = sheet.group()
        if curr_group == PRIMARY_GROUP:
            prev_group = GROUP_CACHE.get(sheet.id(), 5)
            window.move_sheets_to_group([sheet], prev_group)
        else:
            GROUP_CACHE[sheet.id()] = curr_group
            window.move_sheets_to_group([sheet], PRIMARY_GROUP)
        window.focus_group(PRIMARY_GROUP)


class NotedownCheckErrorsCommand(NotedownTextCommand):

    def run(self, edit):
        errors = [] # [(description, name, region)]
        self.check_note_head(errors)
        self.find_broken_links(errors)
        self.show_errors_in_quick_panel(errors)
        self.highlight_errors(errors)

    def check_note_head(self, errors):
        note_view = NotedownView(self.view)
        head_region = note_view.get_head_region()
        head = self.view.substr(head_region)
        if not head:
            errors.append(('Missing head', head, head_region))
            return
        name = note_view.curr_name()
        if name != head:
            errors.append(('Heading is different from name', head, head_region))

    def find_broken_links(self, errors):
        note_view = NotedownView(self.view)
        notes = note_view.find_all_notes()
        for link_region in note_view.find_link_regions():
            link_name = self.view.substr(link_region).lower()
            if link_name not in notes:
                errors.append(('Missing note file', link_name, link_region))

    def goto_error(self, error):
        desc, name, region = error
        self.view.sel().clear()
        self.view.sel().add(region)
        self.view.show(self.view.sel())

    def format_error(self, error):
        desc, name, region = error
        row, _ = self.view.rowcol(region.begin())
        return [desc, 'Line {}: {}'.format(row + 1, name)]

    def show_errors_in_quick_panel(self, errors):
        def on_select(index):
            if index != -1:
                self.goto_error(errors[index])
        self.view.window().show_quick_panel(
            [self.format_error(e) for e in errors], on_select
        )

    def highlight_errors(self, errors):
        self.view.add_regions(
            key='notedown',
            regions=[region for (_, _, region) in errors],
            scope='invalid.illegal',
            icon='',
            flags=sublime.DRAW_NO_FILL
        )


class NotedownAutoRenameCommand(NotedownTextCommand):

    def run(self, edit):
        view = self.auto_rename()
        view.run_command('notedown_check_errors')

    def auto_rename(self):
        note_view = NotedownView(self.view)
        name = note_view.curr_name()
        head = note_view.curr_head()
        if not head or name == head:
            return self.view
        old_file = note_view.curr_file()
        new_file = os.path.join(note_view.curr_dir(), head + '.md')
        text = 'Rename this file to {}?'.format(new_file)
        if not sublime.ok_cancel_dialog(text, 'Rename file'):
            return self.view
        window = self.view.window()
        encoding = self.view.settings().get('default_encoding', 'utf-8')
        self.view.close()
        try:
            os.rename(old_file, new_file)
        except OSError as e:
            sublime.error_message(
                'Failed to rename {}:\n'.format(old_file, e)
            )
            return self.view
        new_view = open_note_file(window, new_file)
        if new_view.is_loading():
            print('loading...', flush=True)
            time.sleep(1)
        self.update_backlinks(name, head, encoding)
        return new_view

    def update_backlinks(self, old_name, new_name, encoding):
        '''
        Logic:
            a -> x ~ y  replace a with x
            a -> a ~ x  do nothing
            a ~ b -> x  replace a and b with x
        '''
        print('\nupdating backlinks')
        old_names = set(old_name.split(NAME_SEP))
        new_names = set(new_name.split(NAME_SEP))
        print(old_names, new_names)

        removed_names = old_names - new_names
        if not removed_names:
            print('no names removed')
            return

        print('trying to update backlinks')
        new_name = LINK_TEMPLATE.format(new_name.split(NAME_SEP)[0])
        pattern = re.compile(r'\[\[({})\]\]'.format('|'.join(removed_names)))

        updated = 0
        notes = NotedownView(self.view).find_all_notes()
        note_files = {n for ns in notes.values() for n in ns}
        print(note_files)

        for note_file in note_files:
            with open(note_file, encoding=encoding) as f:
                try:
                    text, count = pattern.subn(new_name, f.read())
                except UnicodeEncodeError:
                    print('{} is not {} encoded'.format(note_file, encoding))
                    continue
            if count > 0: # links were updated
                print(note_file, count)
                updated += 1
                print('updating backlinks in {}'.format(note_file))
                with open(note_file, 'w', encoding=encoding) as f:
                    f.write(text)

        if updated: # clear cache
            global NOTE_CACHE
            NOTE_CACHE = {}

        return updated


class NotedownEventListener(sublime_plugin.EventListener):

    def on_post_save_async(self, view):
        if viewing_a_note(view):
            view.run_command('notedown_auto_rename')

    def on_hover(self, view, point, hover_zone):
        if viewing_a_note(view) and hover_zone == 1:
            selection = view.extract_scope(point)
            link_text = view.substr(selection)

            if view.match_selector(selection.begin(), WIKI_SELECTOR):
                print("hovering on wiki link: {}".format(repr(link_text)))
                NotedownView(view).open_note_by_name(link_text, primary=True)
