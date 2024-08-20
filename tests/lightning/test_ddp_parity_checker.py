import os
import torch

from megatron.core.optimizer import OptimizerConfig
from nemo import lightning as nl
from nemo.collections import llm
from nemo.lightning.pytorch.callbacks import DdpParityChecker


def make_parser():
    parser = argparse.ArgumentParser(description='Train a small GPT model using NeMo 2.0')
    parser.add_argument('--data-path', type=str, help="Path to data file")
    parser.add_argument('--vocab-path', type=str, help="Path to vocab file")
    parser.add_argument('--merges-path', type=str, help="Path to merges file")

    return parser


def wrap_config(config, trainer):
    class ConfigWrapper(type(config)):
        def configure_model(self, tokenizer) -> "MCoreGPTModel":
            return make_byzantine_model_wrapper(super().configure_model(tokenizer), trainer)

    config.__class__ = ConfigWrapper
    return config


def make_byzantine_model_wrapper(model, trainer):
    class ByzantineModel(type(model)):
        def forward(self, *ans, **kwargs):
            ans = super().forward(*ans, **kwargs)
            with torch.no_grad():
                import random

                rank = int(os.environ['LOCAL_RANK'])
                if rank != 1:
                    return ans
                for opt in trainer.strategy.model.optim._optimizers:
                    for g in opt.param_groups:
                        for param in g['params']:
                            param.fill_(random.uniform(0, 1))
            return ans

    model.__class__ = ByzantineModel
    return model


def test_failing(trainer, ddp_parity, optim, data, tokenizer):
    config = llm.Llama2Config7B(num_layers=2)
    config = wrap_config(config, trainer)
    model = llm.LlamaModel(config, tokenizer=tokenizer, optim=optim)
    trainer.fit(model, data)


def test_working(trainer, ddp_parity, optim, data, tokenizer):
    config = llm.Llama2Config7B(num_layers=2)
    model = llm.LlamaModel(config, tokenizer=tokenizer, optim=optim)
    trainer.fit(model, data)


def make_trainer_optim(args):
    ddp_parity = DdpParityChecker(1)
    trainer = nl.Trainer(
        devices=2,
        max_steps=3,
        accelerator="gpu",
        strategy=nl.MegatronStrategy(
            ckpt_include_optimizer=False,
        ),
        plugins=nl.MegatronMixedPrecision(precision="bf16-mixed"),
        limit_val_batches=0.0,
        num_sanity_val_steps=0,
        log_every_n_steps=1,
        logger=None,
        callbacks=[ddp_parity],
    )

    optim = nl.MegatronOptimizerModule(
        config=OptimizerConfig(
            optimizer="adam",
            lr=1e-5,
            use_distributed_optimizer=False,
            fp16=False,
            bf16=True,
            params_dtype=torch.float32,
        ),
    )

    tokenizer = get_nmt_tokenizer(
        "megatron",
        "GPT2BPETokenizer",
        vocab_file=args.vocab_path,
        merges_file=args.merges_path,
    )
    data = PreTrainingDataModule(
        paths=args.data_path,
        seq_length=2048,
        global_batch_size=32,
        seed=1234,
        tokenizer=tokenizer,
    )

    return trainer, ddp_parity, optim, data, tokenizer


if __name__ == "__main__":

    args = make_parser().parse_args()
    try:
        test_failing(*make_trainer_optim(args))
    except RuntimeError:
        print("DDP parity checking worked as expected.")

    try:
        test_working(*make_trainer_optim(args))
        print("DDP parity checking worked as expected")
    except:
        raise
