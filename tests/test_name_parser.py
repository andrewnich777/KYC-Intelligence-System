"""Tests for multicultural name parser."""

from utilities.name_parser import parse_name


class TestWesternNames:
    def test_simple_western(self):
        nc = parse_name("Sarah Thompson")
        assert nc.given_names == ["Sarah"]
        assert nc.family_name == "Thompson"
        assert nc.original == "Sarah Thompson"

    def test_western_with_middle(self):
        nc = parse_name("Sarah Jane Thompson")
        assert nc.given_names == ["Sarah", "Jane"]
        assert nc.family_name == "Thompson"
        assert nc.first_name == "Sarah"
        assert nc.middle_names == "Jane"

    def test_single_name(self):
        nc = parse_name("Madonna")
        assert nc.family_name == "Madonna"
        assert nc.given_names == []

    def test_honorifics_stripped(self):
        nc = parse_name("Dr. James Smith Jr.")
        assert nc.given_names == ["James"]
        assert nc.family_name == "Smith"
        assert nc.honorifics == ["Dr."]
        assert nc.suffixes == ["Jr."]

    def test_empty_string(self):
        nc = parse_name("")
        assert nc.given_names == []
        assert nc.family_name == ""
        assert nc.original == ""


class TestEastAsianNames:
    def test_chinese_with_hint(self):
        nc = parse_name("Chen Wei Ming", cultural_hint="zh")
        assert nc.family_name == "Chen"
        assert nc.given_names == ["Wei", "Ming"]

    def test_chinese_with_country_hint(self):
        nc = parse_name("Chen Wei Ming", cultural_hint="China")
        assert nc.family_name == "Chen"
        assert nc.given_names == ["Wei", "Ming"]

    def test_japanese_with_hint(self):
        nc = parse_name("Tanaka Yuki", cultural_hint="Japan")
        assert nc.family_name == "Tanaka"
        assert nc.given_names == ["Yuki"]

    def test_korean_with_hint(self):
        nc = parse_name("Kim Soo-jin", cultural_hint="Korea")
        assert nc.family_name == "Kim"
        assert nc.given_names == ["Soo-jin"]


class TestArabicNames:
    def test_arabic_with_al_prefix(self):
        nc = parse_name("Mohammed bin Salman al-Rashid")
        assert nc.family_name == "al-Rashid"
        assert nc.given_names == ["Mohammed"]

    def test_arabic_with_hint(self):
        nc = parse_name("Ahmed Hassan", cultural_hint="Egypt")
        # Without prefix, defaults to western within arabic
        assert nc.family_name == "Hassan"
        assert nc.given_names == ["Ahmed"]

    def test_arabic_ibn(self):
        nc = parse_name("Khalid ibn Abdullah al-Saud")
        assert nc.family_name == "al-Saud"
        assert nc.given_names == ["Khalid"]


class TestHispanicNames:
    def test_hispanic_two_family_names(self):
        nc = parse_name("Carlos Garcia Lopez", cultural_hint="Mexico")
        assert nc.given_names == ["Carlos"]
        assert nc.family_name == "Garcia Lopez"

    def test_hispanic_with_middle(self):
        nc = parse_name("Maria Isabel Garcia Lopez", cultural_hint="Spain")
        assert nc.given_names == ["Maria", "Isabel"]
        assert nc.family_name == "Garcia Lopez"


class TestNameProperties:
    def test_first_name_property(self):
        nc = parse_name("John Michael Smith")
        assert nc.first_name == "John"

    def test_middle_names_property(self):
        nc = parse_name("John Michael David Smith")
        assert nc.middle_names == "Michael David"

    def test_original_preserved(self):
        name = "Dr. Chen Wei Ming Jr."
        nc = parse_name(name, cultural_hint="zh")
        assert nc.original == name


class TestScreeningVariants:
    def test_variants_generated(self):
        from tools.screening_list import _generate_name_variants
        variants = _generate_name_variants("Sarah Thompson")
        assert "Sarah Thompson" in variants
        assert "Thompson Sarah" in variants

    def test_east_asian_variants(self):
        from tools.screening_list import _generate_name_variants
        variants = _generate_name_variants("Chen Wei", cultural_hint="China")
        assert "Chen Wei" in variants
        # Reversed version
        assert any("Wei" in v and "Chen" in v for v in variants)

    def test_deduplication(self):
        from tools.screening_list import _generate_name_variants
        variants = _generate_name_variants("Smith")
        # Single name — all variants should be unique
        assert len(variants) == len(set(variants))
