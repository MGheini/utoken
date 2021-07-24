#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Written by Ulf Hermjakob, USC/ISI
This script is a draft of a tokenizer.
When using STDIN and/or STDOUT, if might be necessary, particularly for older versions of Python, to do
'export PYTHONIOENCODING=UTF-8' before calling this Python script to ensure UTF-8 encoding.
"""
# -*- encoding: utf-8 -*-
import argparse
from itertools import chain
import datetime
import functools
import logging as log
# import os
# from pathlib import Path
import re
import sys
from typing import Optional, TextIO
import unicodedata as ud
from utoken import util

log.basicConfig(level=log.INFO)

__version__ = '0.0.1'
last_mod_date = 'July 23, 2021'


class VertexMap:
    """Maps character positions from current (after insertions/deletions) to original offsets.
    Typical deletions are for many control characters."""
    def __init__(self, s: str):
        self.size = len(s)
        self.char_map_to_orig_start_char = {}
        self.char_map_to_orig_end_char = {}
        for i in range(0, len(s)):
            self.char_map_to_orig_start_char[i] = i
            self.char_map_to_orig_end_char[i+1] = i+1

    def delete_char(self, position, n_characters) -> None:
        """Update VertexMap for deletion of n_characters starting at position."""
        old_len = self.size
        new_len = old_len - n_characters
        for i in range(position, new_len):
            self.char_map_to_orig_start_char[i] = self.char_map_to_orig_start_char[i+n_characters]
            self.char_map_to_orig_end_char[i+1] = self.char_map_to_orig_end_char[i+1+n_characters]
        for i in range(new_len, old_len):
            self.char_map_to_orig_start_char.pop(i, None)
            self.char_map_to_orig_end_char.pop(i+1, None)
        self.size = new_len

    def print(self) -> str:
        result = 'S'
        for i in range(0, self.size):
            result += f' {i}->{self.char_map_to_orig_start_char[i]}'
        result += ' E'
        for i in range(0, self.size):
            result += f' {i+1}->{self.char_map_to_orig_end_char[i+1]}'
        return result


class SimpleSpan:
    """Span from start vertex to end vertex, e.g. 0-1 for first characters.
    Soft version of span can include additional spaces etc. around a token."""
    def __init__(self, hard_from: int, hard_to: int,
                 soft_from: Optional[int] = None, soft_to: Optional[int] = None,
                 vm: Optional[VertexMap] = None):
        if vm:
            self.hard_from = vm.char_map_to_orig_start_char[hard_from]
            self.hard_to = vm.char_map_to_orig_end_char[hard_to]
            self.soft_from = self.hard_from if soft_from is None else vm.char_map_to_orig_start_char[soft_from]
            self.soft_to = self.hard_to if soft_to is None else vm.char_map_to_orig_end_char[soft_to]
        else:
            self.hard_from = hard_from
            self.hard_to = hard_to
            self.soft_from = hard_from if soft_from is None else soft_from
            self.soft_to = hard_to if soft_to is None else soft_to

    def print_hard_span(self) -> str:
        return f'{self.hard_from}-{self.hard_to}'


class ComplexSpan:
    """A complex span is a list of (non-contiguous) spans, e.g. (3-6, 10-13) for the 'cut off' in 'He cut it off.'"""
    def __init__(self, spans: [SimpleSpan]):
        self.spans = spans

    @staticmethod
    def compare_complex_spans(span1, span2) -> bool:
        return span1.spans[0].hard_from - span2.spans[0].hard_from \
            or span1.spans[0].hard_to - span2.spans[0].hard_to

    def print_hard_span(self) -> str:
        self.spans.sort(key=functools.cmp_to_key(ComplexSpan.compare_complex_spans))
        return ','.join(map(SimpleSpan.print_hard_span, self.spans))


class Token:
    """A token is most typically a word, number, or punctuation, but can be a multi-word phrase or part of a word."""
    def __init__(self, surf: str, snt_id: str, creator: str, span: ComplexSpan):
        self.surf = surf
        self.snt_id = snt_id
        self.span = span
        self.creator = creator or "TOKEN"
        self.abbrev_type = None

    def print_short(self) -> str:
        return f'{self.span.print_hard_span()}:{self.creator} {self.surf}'


class Chart:
    def __init__(self, s: str, snt_id: str):
        """A chart is set of spanned tokens."""
        self.orig_s = s     # original sentence
        self.s0 = s         # original sentence without undecodable bytes (only UTF-8 conform characters)
        self.s = s          # current sentence, typically without deletable control characters
        self.snt_id = snt_id
        self.tokens = []
        self.vertex_map = VertexMap(s)

    def delete_char(self, position, n_characters) -> int:
        # function returns number of characters actually deleted
        old_len = len(self.s)
        # sanity check, just in case, but should not happen
        if n_characters + position > old_len:
            n_characters = old_len - position
        if n_characters <= 0:
            return 0
        # update s and vertex_map
        self.s = self.s[:position] + self.s[position+n_characters:]
        self.vertex_map.delete_char(position, n_characters)
        return n_characters

    def register_token(self, token: Token) -> None:
        self.tokens.append(token)

    @staticmethod
    def compare_tokens(token1, token2) -> bool:
        return token1.span.spans[0].hard_from - token2.span.spans[0].hard_from \
            or token1.span.spans[0].hard_to - token2.span.spans[0].hard_to

    def sort_tokens(self) -> None:
        self.tokens.sort(key=functools.cmp_to_key(Chart.compare_tokens))

    def print_short(self) -> str:
        self.sort_tokens()
        return f'Chart {self.snt_id}: ' + ' '.join(map(Token.print_short, self.tokens))

    def print_to_file(self, annotation_file: TextIO) -> None:
        self.sort_tokens()
        annotation_file.write(f'::line {self.snt_id} ::s {self.s0}\n')
        for token in self.tokens:
            annotation_file.write(f'::span {token.span.print_hard_span()} ::type {token.creator} ')
            if token.abbrev_type and token.abbrev_type != 'general':
                annotation_file.write(f'::abbrev-type {token.abbrev_type} ')
            annotation_file.write(f'::surf {token.surf}\n')


class Tokenizer:
    def __init__(self):
        # Ordered list of tokenization steps
        self.tokenization_step_functions = [self.normalize_characters,
                                            self.tokenize_urls,
                                            self.tokenize_emails,
                                            self.tokenize_mt_punctuation,
                                            self.tokenize_numbers,
                                            self.tokenize_abbreviations,
                                            self.tokenize_punctuation,
                                            self.tokenize_main]
        self.next_tokenization_step = {}
        for i in range(0, len(self.tokenization_step_functions)-1):
            self.next_tokenization_step[self.tokenization_step_functions[i]] = self.tokenization_step_functions[i+1]
        self.next_tokenization_step[self.tokenization_step_functions[-1]] = None
        self.char_type_vector_dict = {}
        # Initialize elementary bit vectors (integers each with a different bit set) will be used in bitwise operations.
        # To be expanded.
        self.lv = 0
        bit_vector = 1
        self.char_is_deletable_control_character = bit_vector
        bit_vector = bit_vector << 1
        self.char_is_non_standard_space = bit_vector
        bit_vector = bit_vector << 1
        self.char_is_surrogate = bit_vector
        bit_vector = bit_vector << 1
        self.char_is_ampersand = bit_vector
        self.range_init_char_type_vector_dict()
        self.chart_p = False
        self.first_token_is_line_id_p = False
        self.abbreviation_dict = util.AbbreviationDict()
        self.abbreviation_dict.load_abbreviations('data/abbreviations-eng.txt')
        self.abbreviation_dict.load_abbreviations('data/abbreviations-mal.txt')

    def range_init_char_type_vector_dict(self) -> None:
        # Deletable control characters,
        # keeping zero-width joiner/non-joiner (U+200E/U+200F) for now.
        for code_point in chain(range(0x0000, 0x0009), range(0x000B, 0x000D), range(0x000E, 0x0020), [0x007F],  # C0
                                range(0x0080, 0x00A0),     # C1 block of control characters
                                [0x00AD],                  # soft hyphen
                                [0x0640],                  # Arabic tatweel
                                range(0x200E, 0x2010),     # direction marks
                                range(0xFE00, 0xFE10),     # variation selectors 1-16
                                [0xFEFF],                  # byte order mark, zero width no-break space
                                range(0xE0100, 0xE01F0)):  # variation selectors 17-256
            char = chr(code_point)
            self.char_type_vector_dict[char] \
                = self.char_type_vector_dict.get(char, 0) | self.char_is_deletable_control_character
        # Surrogate
        for code_point in range(0xDC80, 0xDD00):
            char = chr(code_point)
            self.char_type_vector_dict[char] \
                = self.char_type_vector_dict.get(char, 0) | self.char_is_surrogate
        # Non-standard space
        for code_point in chain(range(0x2000, 0x200C), [0x00A0, 0x202F, 0x205F, 0x3000]):
            # A0: NO-BREAK SPACE; 202F: NARROW NO-BREAK SPACE; 205F: MEDIUM MATHEMATICAL SPACE; 3000: IDEOGRAPHIC SPACE
            char = chr(code_point)
            self.char_type_vector_dict[char] \
                = self.char_type_vector_dict.get(char, 0) | self.char_is_non_standard_space
        # Ampersand
        self.char_type_vector_dict['@'] \
            = self.char_type_vector_dict.get('@', 0) | self.char_is_ampersand

    @staticmethod
    def build_rec_result(token_surf: str, s: str, start_position: int, offset: int,
                         token_type: str, line_id: str, chart: Optional[Chart],
                         lang_code: str, ht: dict, this_function):
        """Once a heuristic has identified a particular token span and type,
        this method computes all offsets, creates a new token, and recursively
        calls the calling functions on the string preceding and following the new token.
        The function not only returns the tokenization of the input string, but also the token,
        so that the calling function can assign any further token slot values."""
        offset2 = offset + start_position
        offset3 = offset2 + len(token_surf)
        pre = s[:start_position]
        post = s[start_position + len(token_surf):]
        if chart:
            new_token = Token(token_surf, line_id, token_type,
                              ComplexSpan([SimpleSpan(offset2, offset3, vm=chart.vertex_map)]))
            chart.register_token(new_token)
        else:
            new_token = None
        pre_tokenization = this_function(pre, chart, ht, lang_code, line_id, offset)
        post_tokenization = this_function(post, chart, ht, lang_code, line_id, offset3)
        return util.join_tokens([pre_tokenization, token_surf, post_tokenization]), new_token

    def normalize_characters(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                             line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenizer step deletes non-decodable bytes and most control characters."""
        this_function = self.normalize_characters
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')

        # delete non-decodable bytes (surrogates)
        if self.lv & self.char_is_surrogate:
            deleted_chars = ''
            deleted_positions = []
            s_orig = s
            for i in range(0, len(s_orig)):
                char = s_orig[i]
                if self.char_type_vector_dict.get(char, 0) & self.char_is_surrogate:
                    s = s.replace(char, '')
                    deleted_chars += char
                    deleted_positions.append(str(i))
            n = len(deleted_positions)
            log.warning(f'Warning: In line {line_id}, '
                        f'deleted non-decodable {util.reg_plural("byte", n)} '
                        f'{deleted_chars.encode("ascii", errors="surrogateescape")} '
                        f'from {util.reg_plural("position", n)} {", ".join(deleted_positions)}')
            if chart:
                chart.s0 = s
                chart.s = s

        # delete some control characters, replace non-standard spaces with ASCII space
        if self.lv & self.char_is_deletable_control_character:
            for i in range(len(s)-1, -1, -1):
                if chart:
                    char = chart.s[i]
                    if self.char_type_vector_dict.get(char, 0) & self.char_is_deletable_control_character:
                        chart.delete_char(i, 1)
                    elif self.char_type_vector_dict.get(char, 0) & self.char_is_non_standard_space:
                        chart.s = chart.s.replace(char, ' ')
                else:
                    char = s[i]
                    if self.char_type_vector_dict.get(char, 0) & self.char_is_deletable_control_character:
                        s = s.replace(char, '')
                    elif self.char_type_vector_dict.get(char, 0) & self.char_is_non_standard_space:
                        s = s.replace(char, ' ')
            if chart:
                s = chart.s

        # log.info(f'Normalized line: {s}')
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_urls(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                      line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step splits off URL tokens such as https://www.amazon.com"""
        this_function = self.tokenize_urls
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_str}.{offset}: {s}')
        if ('http' in s) or ('ftp' in s):
            m = re.match(r'(.*)(?<![a-z])((?:https?|ftp)://)(.*)$', s, flags=re.IGNORECASE)
            if m:
                pre = m.group(1)
                anchor = m.group(2)
                post = m.group(3)
                index = 0
                len_post = len(post)
                internal_url_punctuation = "#%&'()*+,-./:;=?@_`~"
                final_url_punctuation = "/"
                # include alphanumeric and certain punctuation characters
                while index < len_post:
                    char = post[index]
                    if char.isalnum():
                        # log.info(f'URL char[{index}]: {char} is alphanumeric')
                        index += 1
                    elif char in internal_url_punctuation:
                        # log.info(f'URL char[{index}]: {char} is internal URL punct')
                        index += 1
                    else:
                        break
                # exclude certain punctuation characters at the end
                while index > 0:
                    char = post[index-1]
                    if char == ')':
                        if '(' in post[0:index-1]:
                            break
                        else:
                            index -= 1
                    elif (char in internal_url_punctuation) and (char not in final_url_punctuation):
                        index -= 1
                    else:
                        break
                # build result
                token_surf = anchor + post[0:index]
                tokenization, new_token = self.build_rec_result(token_surf, s, len(pre), offset,
                                                                'URL', line_id, chart, lang_code, ht,
                                                                this_function)
                return tokenization
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_emails(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                        line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step splits off email-address tokens such as ChunkyLover53@aol.com"""
        this_function = self.tokenize_emails
        this_function_name = this_function.__qualname__
        if self.lv & self.char_is_ampersand:
            pre1 = ''
            s1 = s
            while 1:
                m = re.match(r'(.*?)([a-z][-_.a-z0-9]*[a-z0-9]@[a-z][-_.a-z0-9]*[a-z0-9]\.(?:[a-z]{2,}))(.*)$',
                             s1, flags=re.IGNORECASE)
                if m:
                    pre = m.group(1)
                    token_surf = m.group(2)
                    post = m.group(3)
                    start_position1 = len(pre)
                    left_context = s1[max(0, start_position1 - 4):start_position1]
                    left_context_class = ''.join([('a' if c.isalpha() else 'm' if ud.category(c) == 'Mc'
                                                   else 'd' if c.isdigit() else '-')
                                                  for c in left_context])
                    if (re.match(r'.*(d|am*)$', left_context_class)     # bad left context
                       or (len(post) and post[0].isalnum())):           # bad right context
                        pre1 += pre + token_surf                        # no valid email-address after all
                        s1 = post                                       # look further in post string
                    else:
                        start_position = len(pre1) + start_position1
                        tokenization, new_token = self.build_rec_result(token_surf, s, start_position, offset,
                                                                        'EMAIL-ADDRESS', line_id, chart, lang_code,
                                                                        ht, this_function)
                        return tokenization
                else:
                    break
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_numbers(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                         line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step splits off numbers such as 12,345,678.90"""
        this_function = self.tokenize_numbers
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')
        for start_position in range(0, len(s)):
            char = s[start_position]
            if char.isdigit():
                minus_position = start_position  # i.e. no minus (or plus) sign
                prev_char = s[start_position-1] if start_position > 1 else ' '
                if prev_char in '-−–+':
                    minus_position = start_position-1
                    prev_char = s[minus_position-1] if minus_position > 1 else ' '
                if prev_char in ' ;/([{*%$£€¥₹':
                    right_context = s[start_position+1:min(start_position + 21, len(s))]
                    right_context_class = ''.join([('d' if c.isdigit()
                                                    else c if (c in '.,')
                                                    else '-')
                                                   for c in right_context])
                    m = re.match(r'(d{0,2}(?:,ddd)+(?:\.d+)?|'     # Western style. e.g. 12,345,678.90
                                 r'd?(?:,dd)*,ddd(?:\.d+)?|'       # Indian style, e.g. 1,23,45,678.90
                                 r'd*(?:\.d+)?)'                   # plain, e.g. 12345678.90
                                 r'(.{0,3})', right_context_class)
                    if m:
                        m1 = m.group(1)
                        m2 = m.group(2)
                        m2_class = ''.join([('d' if c.isdigit() else c if (c in ' .,') else '-') for c in m2])
                        if not (re.match(r'[.,]?d', m2_class)):
                            token_surf = s[minus_position:start_position + 1 + len(m1)]
                            # log.info(f'-- {start_position} ({token_surf})')
                            tokenization, new_token = self.build_rec_result(token_surf, s, start_position, offset,
                                                                            'NUMBER', line_id, chart, lang_code,
                                                                            ht, this_function)
                            return tokenization
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_abbreviations(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                               line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step splits off abbreviations ending in a period, searching right to left."""
        this_function = self.tokenize_abbreviations
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')

        for i in range(len(s)-1, -1, -1):
            char = s[i]
            if char == '.':
                start_position = max(0, i - self.abbreviation_dict.max_abbrev_length) - 1
                while start_position+1 < i:
                    start_position += 1
                    if not s[start_position].isalpha():
                        continue  # first character must be a letter
                    if (start_position > 0) and s[start_position-1].isalpha():
                        continue
                    abbrev_cand = s[start_position:i+1]
                    abbrev_entries = self.abbreviation_dict.abbrev_dict.get(abbrev_cand, None)
                    if abbrev_entries:
                        abbrev_entry = abbrev_entries[0]
                        abbrev_type = abbrev_entry.type
                        tokenization, new_token = self.build_rec_result(abbrev_cand, s, start_position, offset,
                                                                        'ABBREV', line_id, chart, lang_code, ht,
                                                                        this_function)
                        if new_token:
                            new_token.abbrev_type = abbrev_type
                        return tokenization
        for start_position in range(0, len(s)-1):
            char = s[start_position]
            if char.isalpha() and char.isupper() and (s[start_position+1] == '.') \
               and ((start_position == 0) or not s[start_position - 1].isalpha()):
                right_context = s[start_position+2:min(start_position+22, len(s))]
                right_context_class = ''.join([('u' if c.isupper()
                                                else 'l' if c.islower()
                                                else c if (c in ' .')
                                                else '-')
                                               for c in right_context])
                if re.match(r'\s?(?:u\.\s?)*ull', right_context_class):
                    token_surf = s[start_position:start_position+2]
                    tokenization, new_token = self.build_rec_result(token_surf, s, start_position, offset, 'ABBREV-I',
                                                                    line_id, chart, lang_code, ht, this_function)
                    return tokenization
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_mt_punctuation(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                                line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step currently splits of dashes in certain contexts."""
        this_function = self.tokenize_mt_punctuation
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')
        for start_position in range(0, len(s)):
            char = s[start_position]
            if char in '-−–—':  # hyphen-minus, minus, ndash, mdash
                end_position = start_position+1
                while end_position < len(s) and s[end_position] in '-−–—':
                    end_position += 1
                left_context = s[max(0, start_position-4):start_position]
                right_context = s[end_position:min(end_position+4, len(s))]
                left_context_class = ''.join([('a' if c.isalpha() else 'm' if ud.category(c) == 'Mc'
                                               else 'd' if c.isdigit() else '-')
                                              for c in left_context])
                right_context_class = ''.join([('a' if c.isalpha() else 'm' if ud.category(c) == 'Mc'
                                                else 'd' if c.isdigit() else '-')
                                               for c in right_context])
                if re.match(r'.*(?:am*am*|d)$', left_context_class) and re.match(r'(?:am*am*|d)', right_context_class):
                    token_surf = s[start_position:end_position]
                    tokenization, new_token = self.build_rec_result(token_surf, s, start_position, offset,
                                                                    'DASH', line_id, chart, lang_code,
                                                                    ht, this_function)
                    return tokenization
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        return s

    def tokenize_punctuation(self, s: str, chart: Chart, ht: dict, lang_code: str = '',
                             line_id: Optional[str] = None, offset: int = 0) -> str:
        """This tokenization step splits off regular punctuation."""
        this_function = self.tokenize_punctuation
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')

        # Some punctuation should always be split off by itself regardless of context:
        # parentheses, brackets, dandas, currency signs.
        m = re.match(r'(.*)(["(){}\[\]〈〉\u3008-\u3011\u3014-\u301B।॥%£€¥₹]|\$+)(.*)$', s)
        if m:
            punct_type = 'PUNCT'
        else:
            # Some punctuation should be split off from the beginning of a token
            # (with a space or sentence-start to the left of the punctuation).
            m = re.match(r'(|.*\s)([\'])(.*)$', s)
            if m:
                punct_type = "PUNCT-S"
            else:
                # Some punctuation should be split off from the end of a token
                # (with a space or sentence-end to the right of the punctuation.
                m = re.match(r'(.*)([\'.?!,;:])(\s.*|)$', s)
                if m:
                    punct_type = "PUNCT-E"
                else:
                    punct_type = ''
        if m:
            pre, token_surf, post = m.group(1), m.group(2), m.group(3)
            tokenization, new_token = self.build_rec_result(token_surf, s, len(pre), offset,
                                                            punct_type, line_id, chart, lang_code, ht,
                                                            this_function)
            return tokenization
        else:
            next_tokenization_function = self.next_tokenization_step[this_function]
            if next_tokenization_function:
                s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
            return s

    def tokenize_main(self, s: str, chart: Chart, ht: dict, lang_code: str = '', line_id: Optional[str] = None,
                      offset: int = 0) -> str:
        """This is the final tokenization step that tokenizes the remaining string by spaces."""
        this_function = self.tokenize_main
        # this_function_name = this_function.__qualname__
        # log.info(f'{this_function_name} l.{line_id}.{offset}: {s}')
        next_tokenization_function = self.next_tokenization_step[this_function]
        if next_tokenization_function:  # Should actually never apply.
            s = next_tokenization_function(s, chart, ht, lang_code, line_id, offset)
        else:
            tokens = []
            index = 0
            start_index = None
            len_s = len(s)
            while index <= len_s:
                char = s[index] if index < len_s else ' '
                if char.isspace():
                    if start_index is not None:
                        token_surf = s[start_index:index]
                        tokens.append(token_surf)
                        if chart:
                            new_token = Token(token_surf, str(line_id), 'MAIN',
                                              ComplexSpan([SimpleSpan(offset+start_index, offset+index,
                                                                      vm=chart.vertex_map)]))
                            chart.register_token(new_token)
                        # log.info(f'MAIN {line_id}:{start_index}-{index} {token_surf}')
                        start_index = None
                elif start_index is None:
                    start_index = index
                index += 1
            s = util.join_tokens(tokens)
        return s

    def tokenize_string(self, s: str, ht: dict, lang_code: str = '', line_id: Optional[str] = None,
                        annotation_file: Optional[TextIO] = None) -> str:
        self.lv = 0  # line_char_type_vector
        # Each bit in this vector is to capture character type info, e.g. char_is_arabic
        # Build a bit-vector for the whole line, as the bitwise 'or' of all character bit-vectors.
        for char in s:
            char_type_vector = self.char_type_vector_dict.get(char, 0)
            if char_type_vector:
                # A set bit in the lv means that the bit has been set by at least one char.
                # So we will easily know whether e.g. a line contains a digit.
                # If not, some digit-specific tokenization steps can be skipped to improve run-time.
                self.lv = self.lv | char_type_vector
        # Initialize chart.
        chart = Chart(s, line_id) if self.chart_p else None
        # Call the first tokenization step function, which then recursively call all other tokenization step functions.
        first_tokenization_step_function = self.tokenization_step_functions[0]
        s = first_tokenization_step_function(s, chart, ht, lang_code, line_id)
        if chart:
            log.info(chart.print_short())  # Temporary. Will print short version of chart to STDERR.
            if annotation_file:
                chart.print_to_file(annotation_file)
        return s.strip()

    def tokenize_lines(self, ht: dict, input_file: TextIO, output_file: TextIO, annotation_file: Optional[TextIO],
                       lang_code=''):
        """Apply normalization/cleaning to a file (or STDIN/STDOUT)."""
        line_number = 0
        for line in input_file:
            line_number += 1
            ht['NUMBER-OF-LINES'] = line_number
            if self.first_token_is_line_id_p:
                m = re.match(r'(\S+)(\s+)(\S|\S.*\S)\s*$', line)
                if m:
                    line_id = m.group(1)
                    line_id_sep = m.group(2)
                    core_line = m.group(3)
                    output_file.write(line_id + line_id_sep
                                      + self.tokenize_string(core_line, ht, lang_code=lang_code,
                                                             line_id=line_id, annotation_file=annotation_file)
                                      + "\n")
            else:
                output_file.write(self.tokenize_string(line.rstrip("\n"), ht, lang_code=lang_code,
                                                       line_id=str(line_number), annotation_file=annotation_file)
                                  + "\n")


def main(argv):
    """Wrapper around tokenization that takes care of argument parsing and prints change stats to STDERR."""
    # parse arguments
    parser = argparse.ArgumentParser(description='Tokenizes a given text')
    parser.add_argument('-i', '--input', type=argparse.FileType('r', encoding='utf-8', errors='surrogateescape'),
                        default=sys.stdin, metavar='INPUT-FILENAME', help='(default: STDIN)')
    parser.add_argument('-o', '--output', type=argparse.FileType('w', encoding='utf-8', errors='ignore'),
                        default=sys.stdout, metavar='OUTPUT-FILENAME', help='(default: STDOUT)')
    parser.add_argument('-a', '--annotation', type=argparse.FileType('w', encoding='utf-8', errors='ignore'),
                        default=None, metavar='ANNOTATION-FILENAME', help='(optional output)')
    parser.add_argument('--lc', type=str, default='', metavar='LANGUAGE-CODE', help="ISO 639-3, e.g. 'fas' for Persian")
    parser.add_argument('-f', '--first_token_is_line_id', action='count', default=0, help='First token is line ID')
    parser.add_argument('-v', '--verbose', action='count', default=0, help='write change log etc. to STDERR')
    parser.add_argument('-c', '--chart', action='count', default=0, help='build chart, even without annotation output')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {__version__} last modified: {last_mod_date}')
    args = parser.parse_args(argv)
    lang_code = args.lc
    tok = Tokenizer()
    tok.chart_p = bool(args.annotation) or bool(args.chart)
    tok.first_token_is_line_id_p = bool(args.first_token_is_line_id)

    # Open any input or output files. Make sure utf-8 encoding is properly set (in older Python3 versions).
    if args.input is sys.stdin and not re.search('utf-8', sys.stdin.encoding, re.IGNORECASE):
        log.error(f"Bad STDIN encoding '{sys.stdin.encoding}' as opposed to 'utf-8'. \
                    Suggestion: 'export PYTHONIOENCODING=UTF-8' or use '--input FILENAME' option")
    if args.output is sys.stdout and not re.search('utf-8', sys.stdout.encoding, re.IGNORECASE):
        log.error(f"Error: Bad STDIN/STDOUT encoding '{sys.stdout.encoding}' as opposed to 'utf-8'. \
                    Suggestion: 'export PYTHONIOENCODING=UTF-8' or use use '--output FILENAME' option")

    ht = {}
    start_time = datetime.datetime.now()
    if args.verbose:
        log.info(f'Start: {start_time}')
        log.info('Script tokenize.py')
        if args.input is not sys.stdin:
            log.info(f'Input: {args.input.name}')
        if args.output is not sys.stdout:
            log.info(f'Output: {args.output.name}')
        if args.annotation:
            log.info(f'Annotation: {args.annotation.name}')
        if tok.chart_p:
            log.info(f'Chart to be built: {tok.chart_p}')
        if lang_code:
            log.info(f'ISO 639-3 language code: {lang_code}')
    tok.tokenize_lines(ht, input_file=args.input, output_file=args.output, annotation_file=args.annotation,
                       lang_code=lang_code)
    # Log some change stats.
    if args.verbose:
        number_of_lines = ht.get('NUMBER-OF-LINES', 0)
        lines = 'line' if number_of_lines == 1 else 'lines'
        log_info = f"Processed {str(number_of_lines)} {lines}"
        log.info(log_info)
        end_time = datetime.datetime.now()
        log.info(f'End: {end_time}')
        elapsed_time = end_time - start_time
        log.info(f'Time: {elapsed_time}')


if __name__ == "__main__":
    main(sys.argv[1:])
