use bullet::{
    game::inputs::{Chess768, ChessBucketsMirrored, get_num_buckets},
    nn::{InitSettings, Shape, optimiser::AdamW},
    trainer::{
        save::SavedFormat,
        schedule::{TrainingSchedule, TrainingSteps, lr, wdl},
        settings::{LocalSettings, TestDataset},
    },
    value::{ValueTrainerBuilder, loader::DirectSequentialDataLoader},
};

const QA: i16 = 255;
const QB: i16 = 64;
#[rustfmt::skip]
const BUCKET_LAYOUT: [usize; 32] = [
    0, 1, 2, 3,
    4, 4, 5, 5,
    6, 6, 6, 6,
    7, 7, 7, 7,
    8, 8, 8, 8,
    8, 8, 8, 8,
    9, 9, 9, 9,
    9, 9, 9, 9,
];
const KING_BUCKETS: usize = get_num_buckets(&BUCKET_LAYOUT);

fn train<const HIDDEN: usize>(data: &str, validation: &str,
                              batches_per_superbatch: usize, wdl_blend: f32,
                              tag: &str) {
    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(Chess768)
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        .build(|builder, stm, ntm| {
            let l0 = builder.new_affine("l0", 768, HIDDEN);
            let l1 = builder.new_affine("l1", 2 * HIDDEN, 1);
            l1.forward(l0.forward(stm).screlu().concat(l0.forward(ntm).screlu()))
        });

    let schedule = TrainingSchedule {
        net_id: format!("minimal-chess-768x{HIDDEN}-{tag}-wdl{:03}",
                        (100.0 * wdl_blend).round() as u32),
        eval_scale: 400.0,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch,
            start_superbatch: 1,
            end_superbatch: 40,
        },
        wdl_scheduler: wdl::ConstantWDL { value: wdl_blend },
        lr_scheduler: lr::CosineDecayLR {
            initial_lr: 0.001,
            final_lr: 0.001 * 0.3_f32.powi(5),
            final_superbatch: 40,
        },
        save_rate: 10,
    };
    let settings = LocalSettings {
        // Keep host-side loading light so engine-testing/SPSA can retain CPU time.
        threads: 1,
        test_set: Some(TestDataset { path: validation, freq: batches_per_superbatch }),
        output_directory: "checkpoints",
        batch_queue_size: 64,
    };
    trainer.run(&schedule, &settings, &DirectSequentialDataLoader::new(&[data]));
}

fn train_king_buckets<const HIDDEN: usize>(data: &str, validation: &str,
                                            batches_per_superbatch: usize,
                                            wdl_blend: f32, tag: &str) {
    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(ChessBucketsMirrored::new(BUCKET_LAYOUT))
        .save_format(&[
            SavedFormat::id("l0w")
                .transform(|store, weights| {
                    let factoriser = store.get("l0f").values.f32().repeat(KING_BUCKETS);
                    weights.into_iter().zip(factoriser).map(|(a, b)| a + b).collect()
                })
                .round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        .build(|builder, stm, ntm| {
            let l0f = builder.new_weights("l0f", Shape::new(HIDDEN, 768), InitSettings::Zeroed);
            let mut l0 = builder.new_affine("l0", 768 * KING_BUCKETS, HIDDEN);
            l0.weights = l0.weights + l0f.repeat(KING_BUCKETS);
            let l1 = builder.new_affine("l1", 2 * HIDDEN, 1);
            l1.forward(l0.forward(stm).screlu().concat(l0.forward(ntm).screlu()))
        });

    let schedule = TrainingSchedule {
        net_id: format!("minimal-chess-king10x{HIDDEN}-{tag}-wdl{:03}",
                        (100.0 * wdl_blend).round() as u32),
        eval_scale: 400.0,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch,
            start_superbatch: 1,
            end_superbatch: 40,
        },
        wdl_scheduler: wdl::ConstantWDL { value: wdl_blend },
        lr_scheduler: lr::CosineDecayLR {
            initial_lr: 0.001,
            final_lr: 0.001 * 0.3_f32.powi(5),
            final_superbatch: 40,
        },
        save_rate: 10,
    };
    let settings = LocalSettings {
        threads: 1,
        test_set: Some(TestDataset { path: validation, freq: batches_per_superbatch }),
        output_directory: "checkpoints",
        batch_queue_size: 64,
    };
    trainer.run(&schedule, &settings, &DirectSequentialDataLoader::new(&[data]));
}

fn main() {
    let data = std::env::args().nth(1).unwrap_or_else(|| "data/baseline.data".into());
    let validation = std::env::args().nth(2).unwrap_or_else(|| "data/validation.data".into());
    let batches_per_superbatch = std::env::args().nth(3)
        .map(|value| value.parse().expect("batches per superbatch must be an integer"))
        .unwrap_or(337);
    let wdl_blend: f32 = std::env::args().nth(4)
        .map(|value| value.parse().expect("WDL blend must be between 0 and 1"))
        .unwrap_or(0.0);
    let hidden: usize = std::env::args().nth(5)
        .map(|value| value.parse().expect("hidden size must be 128, 256, or 512"))
        .unwrap_or(128);
    let tag = std::env::args().nth(6).unwrap_or_else(|| "baseline".into());
    let architecture = std::env::args().nth(7).unwrap_or_else(|| "plain".into());
    assert!(tag.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '-'),
            "checkpoint tag may contain only letters, digits, and hyphens");
    assert!((0.0..=1.0).contains(&wdl_blend), "WDL blend must be between 0 and 1");
    match (architecture.as_str(), hidden) {
        ("plain", 128) => train::<128>(&data, &validation, batches_per_superbatch, wdl_blend, &tag),
        ("plain", 256) => train::<256>(&data, &validation, batches_per_superbatch, wdl_blend, &tag),
        ("plain", 512) => train::<512>(&data, &validation, batches_per_superbatch, wdl_blend, &tag),
        ("king10", 128) => train_king_buckets::<128>(&data, &validation, batches_per_superbatch, wdl_blend, &tag),
        ("king10", 256) => train_king_buckets::<256>(&data, &validation, batches_per_superbatch, wdl_blend, &tag),
        _ => panic!("architecture/hidden must be plain 128/256/512 or king10 128/256"),
    }
}
