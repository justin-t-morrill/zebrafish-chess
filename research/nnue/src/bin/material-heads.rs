use bullet::{
    game::{formats::bulletformat::ChessBoard, inputs::Chess768, outputs::OutputBuckets},
    nn::optimiser::AdamW,
    trainer::{
        save::SavedFormat,
        schedule::{TrainingSchedule, TrainingSteps, lr, wdl},
        settings::{LocalSettings, TestDataset},
    },
    value::{ValueTrainerBuilder, loader::DirectSequentialDataLoader},
};
use std::{env, fs};

#[derive(Clone, Copy, Default)]
struct MaterialHeads;

impl OutputBuckets<ChessBoard> for MaterialHeads {
    const BUCKETS: usize = 4;
    fn bucket(&self, board: &ChessBoard) -> u8 {
        ((board.occ().count_ones().saturating_sub(1) / 8).min(3)) as u8
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    assert_eq!(
        args.len(),
        10,
        "usage: material-heads TRAIN VALIDATION INITIAL_WEIGHTS OUTPUT_DIR TAG WIDTH BATCHES_PER_SUPERBATCH SUPERBATCHES INITIAL_LR"
    );
    let hidden: usize = args[6].parse().expect("width");
    let batches: usize = args[7].parse().expect("batches per superbatch");
    let steps: usize = args[8].parse().expect("superbatches");
    let initial_lr: f32 = args[9].parse().expect("learning rate");
    assert!(matches!(hidden, 128 | 256 | 512));
    assert!(batches > 0 && steps >= 2 && initial_lr.is_finite() && initial_lr > 0.0);

    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(Chess768)
        .output_buckets(MaterialHeads)
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(255),
            SavedFormat::id("l0b").round().quantise::<i16>(255),
            SavedFormat::id("l1w")
                .round()
                .quantise::<i16>(64)
                .transpose(),
            SavedFormat::id("l1b").round().quantise::<i16>(16320),
        ])
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        .build(|builder, stm, ntm, bucket| {
            let l0 = builder.new_affine("l0", 768, hidden);
            let l1 = builder.new_affine("l1", 2 * hidden, 4);
            let features = l0.forward(stm).screlu().concat(l0.forward(ntm).screlu());
            l1.forward(features).select(bucket)
        });
    trainer
        .optimiser
        .load_weights_from_file(&args[3])
        .expect("warm start");
    let schedule = TrainingSchedule {
        net_id: args[5].clone(),
        eval_scale: 400.0,
        steps: TrainingSteps {
            batch_size: 16384,
            batches_per_superbatch: batches,
            start_superbatch: 1,
            end_superbatch: steps,
        },
        wdl_scheduler: wdl::ConstantWDL { value: 0.0 },
        lr_scheduler: lr::CosineDecayLR {
            initial_lr,
            final_lr: initial_lr * 0.05,
            final_superbatch: steps,
        },
        save_rate: (steps / 4).max(1),
    };
    fs::create_dir_all(&args[4]).expect("checkpoint directory");
    let settings = LocalSettings {
        threads: 2,
        test_set: Some(TestDataset {
            path: &args[2],
            freq: batches,
        }),
        output_directory: &args[4],
        batch_queue_size: 16,
    };
    trainer.run(
        &schedule,
        &settings,
        &DirectSequentialDataLoader::new(&[&args[1]]),
    );
}
