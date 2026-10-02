"""Readable, farm-themed filler text (in the spirit of the old M00M00 / MeowMeow examples).

A Faker provider, so it draws from Faker's seeded random and stays deterministic
under the Build's per-(handle, field) reseeding. Everything here is obviously
fictional: no real institutions, journals, or people.
"""

from faker.providers import BaseProvider

ANIMALS = {
    # animal: (plural, sound, adjective, collective)
    "cow": ("cows", "Moo", "Bovine", "herd"),
    "cat": ("cats", "Meow", "Feline", "clowder"),
    "goat": ("goats", "Maa", "Caprine", "herd"),
    "sheep": ("sheep", "Baa", "Ovine", "flock"),
    "pig": ("pigs", "Oink", "Porcine", "sounder"),
    "hen": ("hens", "Cluck", "Galline", "brood"),
    "duck": ("ducks", "Quack", "Anatine", "paddling"),
    "horse": ("horses", "Neigh", "Equine", "stable"),
    "llama": ("llamas", "Hum", "Camelid", "herd"),
    "dog": ("dogs", "Woof", "Canine", "pack"),
}
PLACES = [
    "Meadowbrook",
    "Clover Hill",
    "Haystack Valley",
    "Willow Creek",
    "Barnstead",
    "Pasture Point",
    "Oakpaddock",
    "Sunny Acres",
    "Fernfield",
    "Millpond",
]
INSTITUTION_KINDS = [
    "Institute of {adj} Studies",
    "College of {adj} Medicine",
    "Center for {adj} Genomics",
    "{adj} Research Cooperative",
    "School of Barnyard Sciences",
    "Agricultural Health Consortium",
]
DESIGNS = [
    "Longitudinal",
    "Cross-Sectional",
    "Natural History",
    "Family-Based",
    "Prospective",
    "Pilot",
    "Multi-Farm",
]
STUDY_NOUNS = ["Cohort", "Study", "Registry", "Project", "Survey", "Initiative"]
# Topics are singular noun phrases that fit any of the animals.
TOPICS = [
    "early development",
    "coat color",
    "seasonal activity",
    "growth rate",
    "heart murmur prevalence",
    "thyroid function",
    "sleep quality",
    "appetite",
    "hearing",
    "social behavior",
    "litter size",
    "lifespan",
]
FINDINGS = [
    "varies with the season",
    "runs in families",
    "changes with age",
    "differs between farms",
    "tracks with diet",
    "is mostly unremarkable",
]
JOURNALS = [
    "J Barnyard Sci",
    "Pasture Med Rev",
    "Ann Hayloft Genet",
    "Proc Farmstead Soc",
    "Int J Clover Res",
]
FIRST_INITIALS = "ABCDEFGHJKLMNPRSTW"
VBR_KINDS = ["Specimen Barn", "Biorepository", "Sample Silo", "Cold Storage Shed"]
ENCOUNTER_KINDS = [
    "Baseline visit",
    "Follow-up visit",
    "Annual check-up",
    "Shearing-season visit",
    "Pasture visit",
    "Milestone review",
]
ACTIVITIES = [
    "Clinical assessment",
    "Blood draw",
    "Saliva collection",
    "Whole genome sequencing",
    "Hoof and coat exam",
    "Growth measurement",
    "Hearing check",
    "Questionnaire",
]


def theme_animal(index: int) -> str:
    """The animal for a record, from a number the Build derives from its handle."""
    names = sorted(ANIMALS)
    return names[index % len(names)]


class BarnyardProvider(BaseProvider):
    # Set by the Build before each use so all fields of one record share an animal.
    theme: str | None = None

    def _animal(self) -> tuple[str, str, str, str, str]:
        animal = self.theme or self.random_element(sorted(ANIMALS))
        return (animal, *ANIMALS[animal])

    def study_title(self) -> str:
        _, _, sound, adj, _ = self._animal()
        return f"{sound}{sound} {self.random_element(DESIGNS)} {adj} {self.random_element(STUDY_NOUNS)}"

    def study_description(self) -> str:
        _, plural, _, _, collective = self._animal()
        topic, other = self.random_sample(TOPICS, length=2)
        place = self.random_element(PLACES)
        return (
            f"A fictional study of {topic} in {plural} raised on farms around {place}. "
            f"Each {collective} is followed with regular visits, and {other} is "
            f"recorded along the way. All participants and data are synthetic."
        )

    def access_description(self) -> str:
        _, _, _, adj, _ = self._animal()
        return self.random_element(
            [
                f"Data may be used for any research on {adj.lower()} health.",
                "Open to general research use; please credit the farm.",
                "Approved researchers only; no commercial use of the herd's data.",
                f"Use limited to studies of {self.random_element(TOPICS)}.",
            ]
        )

    def institution(self) -> str:
        _, _, _, adj, _ = self._animal()
        kind = self.random_element(INSTITUTION_KINDS).format(adj=adj)
        return f"{self.random_element(PLACES)} {kind}"

    def repository_name(self) -> str:
        return f"{self.random_element(PLACES)} {self.random_element(VBR_KINDS)}"

    def _author(self) -> str:
        sound = ANIMALS[self.random_element(sorted(ANIMALS))][
            1
        ]  # co-authors from any farm
        return f"{sound} {self.random_element(FIRST_INITIALS)}"

    def bibliographic_reference(self) -> str:
        _, plural, _, _, _ = self._animal()
        authors = ", ".join(self._author() for _ in range(self.random_int(2, 4)))
        topic = self.random_element(TOPICS)
        year = self.random_int(2015, 2025)
        vol, issue, page = (
            self.random_int(3, 40),
            self.random_int(1, 12),
            self.random_int(1, 300),
        )
        title = (
            f"{topic[0].upper()}{topic[1:]} in {plural} {self.random_element(FINDINGS)}"
        )
        return f"{authors}. {title}. {self.random_element(JOURNALS)}. {year};{vol}({issue}):{page}-{page + self.random_int(4, 20)}."

    def encounter_name(self) -> str:
        return str(self.random_element(ENCOUNTER_KINDS))

    def activity_name(self) -> str:
        return str(self.random_element(ACTIVITIES))

    def dataset_name(self) -> str:
        _, _, sound, adj, _ = self._animal()
        return f"{sound}{sound} {adj} data release {self.random_int(1, 5)}"
