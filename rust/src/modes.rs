//! Built-in animation catalogue, taken verbatim from the APK resources.
//! Generated from the Python catalogue; do not edit by hand.

#[derive(Clone, Copy, Debug)]
pub struct ModeCategory {
    pub name: &'static str,
    pub hidden: bool,
    pub modes: &'static [(i32, &'static str)],
}

pub const CATEGORIES: &[ModeCategory] = &[
    ModeCategory {
        name: "Basic",
        hidden: false,
        modes: &[
            (1, "Automatic loop"),
            (2, "Symphony"),
            (3, "Colorful energy"),
            (4, "Colorful jumps"),
            (7, "7 colors strobe"),
            (10, "7 colors gradient"),
            (26, "Colorful fluttering"),
            (27, "Red-green-blue fluttering"),
            (29, "Colorful brushing"),
            (30, "Red-green-blue color brushing"),
            (31, "Yellow-cyan-purple color brushing"),
            (32, "Colorful brush color brush closed-pull"),
        ],
    },
    ModeCategory {
        name: "Opening & closing",
        hidden: false,
        modes: &[
            (35, "7 colors opening-closing"),
            (36, "Red-green-blue opening-closing"),
            (37, "Yellow-cyan-purple opening-closes"),
            (38, "Red opening-closing"),
            (39, "Green opening-closing"),
            (40, "Blue opening-closing"),
            (41, "Yellow opening-closing"),
            (42, "Cyan opening-closing"),
            (43, "purple opening-closing"),
            (44, "White opening-closing"),
        ],
    },
    ModeCategory {
        name: "Transition",
        hidden: false,
        modes: &[
            (45, "7 colors light-dark transition"),
            (46, "Blue-red-green light-dark transition"),
            (47, "Violet-green-yellow light-dark transition"),
            (48, "6 colors light-dark transition red"),
            (49, "6 colors light-dark transition green"),
            (50, "6 colors light-dark transition blue"),
            (51, "6 colors light-dark transition cyan"),
            (52, "6 colors light-dark transition yellow"),
            (53, "6 colors light-dark transition purple"),
            (54, "6 colors light-dark transition white"),
        ],
    },
    ModeCategory {
        name: "Running water",
        hidden: false,
        modes: &[
            (55, "7 colors flowing water"),
            (56, "Blue-green-red running water"),
            (57, "Purple-green-yellow running water"),
            (58, "Red-green running water"),
            (59, "Green-blue running water"),
            (60, "Yellow-blue running water"),
            (61, "Yellow-cyan running water"),
            (62, "Blue-purple running water"),
        ],
    },
    ModeCategory {
        name: "Tailing",
        hidden: false,
        modes: &[
            (76, "7 colors trailing"),
            (77, "Red trailing"),
            (78, "Green trailing"),
            (79, "Blue trailing"),
            (80, "Yellow trailing"),
            (81, "Cyan tailing"),
            (82, "Purple tailing"),
            (83, "White trailing"),
        ],
    },
    ModeCategory {
        name: "Running",
        hidden: false,
        modes: &[
            (84, "Red running"),
            (85, "Green running"),
            (86, "Blue running"),
            (87, "Yellow running"),
            (88, "Cyan running"),
            (89, "Purple running"),
            (90, "White running"),
            (91, "7 colors running"),
            (92, "Blue-green-red running"),
            (93, "Purple-cyan-yellow running"),
        ],
    },
    ModeCategory {
        name: "Flow",
        hidden: true,
        modes: &[
            (63, "Black-white running water"),
            (64, "White-red-white flow"),
            (65, "White-green-white flow"),
            (66, "White-blue-white flow"),
            (67, "White-yellow-white flow"),
            (68, "White-green-white flow"),
            (69, "White purple-white flow"),
            (70, "Red-white-red flow"),
            (71, "Green-white-green flow"),
            (72, "Blue-white-blue flow"),
            (73, "yellow-white-yellow flow"),
            (74, "Blue-white-blue flow"),
            (75, "Purple-white-purple flow"),
        ],
    },
];

pub fn category_by_name(name: &str) -> Option<&'static ModeCategory> {
    CATEGORIES.iter().find(|category| category.name == name)
}

pub fn mode_name(mode_id: i32) -> Option<&'static str> {
    CATEGORIES
        .iter()
        .flat_map(|category| category.modes.iter())
        .find(|(id, _)| *id == mode_id)
        .map(|(_, name)| *name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalogue_matches_apk_size() {
        let visible: usize = CATEGORIES
            .iter()
            .filter(|category| !category.hidden)
            .map(|category| category.modes.len())
            .sum();
        let hidden: usize = CATEGORIES
            .iter()
            .filter(|category| category.hidden)
            .map(|category| category.modes.len())
            .sum();
        assert_eq!(visible, 58);
        assert_eq!(hidden, 13);
        assert_eq!(visible + hidden, 71);
        assert_eq!(mode_name(93), Some("Purple-cyan-yellow running"));
    }
}
